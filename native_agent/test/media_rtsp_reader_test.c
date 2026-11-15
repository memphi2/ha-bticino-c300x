#include "../src/media_rtsp_reader.h"
#include "../src/time_util.h"

#include <assert.h>
#include <fcntl.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static const char request[] = "SET_PARAMETER rtsp://local/doorbell RTSP/1.0\r\n"
    "Content-Length: 3\r\n\r\na\0b";
static const unsigned char frame[] = {'$', 7, 0, 4, 0, 1, 2, 255};

typedef struct {
    int fds[2];
    unsigned char storage[512];
    rtsp_read_buffer_t buffer;
    char request[256];
    unsigned char payload[16];
    int channel;
    size_t length;
} reader_t;

static void init(reader_t *reader)
{
    memset(reader, 0, sizeof(*reader));
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, reader->fds) == 0);
    reader->buffer = (rtsp_read_buffer_t){reader->storage, sizeof(reader->storage), 0, 0, 0};
}

static void finish(reader_t *reader)
{
    /* The reader only borrows the socket, even after EOF/error/timeout. */
    assert(fcntl(reader->fds[1], F_GETFD) >= 0);
    close(reader->fds[0]);
    close(reader->fds[1]);
}

static rtsp_read_result_t next(reader_t *reader)
{
    return c300x_media_rtsp_read(&reader->buffer, reader->fds[1],
        reader->request, sizeof(reader->request), reader->payload, sizeof(reader->payload),
        &reader->channel, &reader->length, 1);
}

static void put(reader_t *reader, const void *data, size_t length)
{
    assert(send(reader->fds[0], data, length, 0) == (ssize_t)length);
}

static void mixed_frames(void)
{
    unsigned char wire[256];
    size_t request_len = sizeof(request) - 1;
    size_t size = sizeof(frame) + request_len + sizeof(frame);
    memcpy(wire, frame, sizeof(frame));
    memcpy(wire + sizeof(frame), request, request_len);
    memcpy(wire + sizeof(frame) + request_len, frame, sizeof(frame));
    /* Every prefix split, including compacting a partially consumed buffer. */
    for (size_t split = 0; split <= size; split++) {
        reader_t reader;
        init(&reader);
        reader.buffer.start = 9;
        reader.buffer.len = split;
        memcpy(reader.storage + reader.buffer.start, wire, split);
        put(&reader, wire + split, size - split);
        assert(next(&reader) == RTSP_READ_INTERLEAVED);
        assert(reader.channel == 7 && reader.length == 4);
        assert(memcmp(reader.payload, frame + 4, 4) == 0);
        assert(reader.request[0] == '\0');
        assert(next(&reader) == RTSP_READ_REQUEST);
        assert(memcmp(reader.request, request, sizeof(request)) == 0);
        assert(reader.channel == -1 && reader.length == 0);
        assert(next(&reader) == RTSP_READ_INTERLEAVED);
        assert(reader.channel == 7 && reader.length == 4);
        assert(reader.buffer.len == 0 && reader.buffer.start == 0);
        finish(&reader);
    }
}

static void discarded_frames(void)
{
    unsigned char oversized[604] = {'$', 9, 2, 88};
    for (size_t buffered = 0; buffered <= 40; buffered += 4) {
        reader_t reader;
        init(&reader);
        reader.buffer.cap = 128;
        memcpy(reader.storage, oversized, buffered);
        reader.buffer.len = buffered;
        put(&reader, oversized + buffered, sizeof(oversized) - buffered);
        put(&reader, request, sizeof(request) - 1);
        assert(next(&reader) == RTSP_READ_INTERLEAVED);
        assert(reader.channel == 9 && reader.length == 0);
        assert(next(&reader) == RTSP_READ_REQUEST);
        assert(memcmp(reader.request, request, sizeof(request)) == 0);
        finish(&reader);
    }
    reader_t reader;
    init(&reader);
    put(&reader, "$\003\0\0", 4);
    assert(next(&reader) == RTSP_READ_INTERLEAVED);
    assert(reader.channel == 3 && reader.length == 0);
    finish(&reader);
}

static void limits(void)
{
    reader_t reader;
    init(&reader);
    reader.buffer.cap = 8;
    put(&reader, "OPTIONS long", 12);
    assert(next(&reader) == RTSP_READ_ERROR);
    finish(&reader);

    init(&reader);
    const char oversized_request[] = "SET_PARAMETER x RTSP/1.0\r\nContent-Length: 512\r\n\r\n";
    put(&reader, oversized_request, sizeof(oversized_request) - 1);
    assert(next(&reader) == RTSP_READ_ERROR);
    finish(&reader);

    init(&reader);
    assert(c300x_media_rtsp_read(NULL, -1, reader.request, sizeof(reader.request),
        reader.payload, sizeof(reader.payload), &reader.channel, &reader.length, 1) == RTSP_READ_ERROR);
    assert(c300x_media_rtsp_read(&reader.buffer, -1, reader.request, 1,
        reader.payload, sizeof(reader.payload), &reader.channel, &reader.length, 1) == RTSP_READ_ERROR);
    finish(&reader);
}

static void deadlines_and_eof(void)
{
    const char *partials[] = {"", "$", "$\001\0\004xy", "OPTIONS ",
        "SET_PARAMETER x RTSP/1.0\r\nContent-Length: 3\r\n\r\nx"};
    for (int eof = 0; eof < 2; eof++) {
        for (size_t i = 0; i < sizeof(partials) / sizeof(partials[0]); i++) {
            reader_t reader;
            init(&reader);
            put(&reader, partials[i], i == 2 ? 6 : strlen(partials[i]));
            if (eof) assert(shutdown(reader.fds[0], SHUT_WR) == 0);
            long long start = c300x_monotonic_ms();
            reader.buffer.deadline_ms = start + 30;
            assert(next(&reader) == (!eof && i == 0 ? RTSP_READ_TIMEOUT : RTSP_READ_ERROR));
            assert(c300x_monotonic_ms() - start < 1000);
            finish(&reader);
        }
    }
}

int main(void)
{
    mixed_frames();
    discarded_frames();
    limits();
    deadlines_and_eof();
    return 0;
}
