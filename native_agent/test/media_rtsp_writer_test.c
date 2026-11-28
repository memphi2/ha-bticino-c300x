/* Exercise production writes with deterministic short-write interleavings. */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <sys/socket.h>
#include <unistd.h>

static ssize_t short_sendmsg(int, const struct msghdr *, int);
static int observed_trylock(pthread_mutex_t *);
#define sendmsg short_sendmsg
#define pthread_mutex_trylock observed_trylock
#include "../src/media_rtsp_io.c"
#undef pthread_mutex_trylock
#undef sendmsg

static pthread_mutex_t barrier = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static pthread_mutex_t *observed_mutex;
static int short_fd = -1;
static bool paused, resume_write, contender_seen, fail_remainder;

static int observed_trylock(pthread_mutex_t *mutex)
{
    int result = pthread_mutex_trylock(mutex);
    pthread_mutex_lock(&barrier);
    if (mutex == observed_mutex && result == EBUSY) {
        contender_seen = true;
        pthread_cond_broadcast(&changed);
    }
    pthread_mutex_unlock(&barrier);
    return result;
}

static ssize_t short_sendmsg(int fd, const struct msghdr *message, int flags)
{
    pthread_mutex_lock(&barrier);
    if (fd != short_fd) {
        pthread_mutex_unlock(&barrier);
        return sendmsg(fd, message, flags);
    }
    if (paused) {
        bool fail = fail_remainder;
        pthread_mutex_unlock(&barrier);
        if (fail) { errno = EPIPE; return -1; }
        return sendmsg(fd, message, flags);
    }
    struct iovec parts[2];
    size_t remaining = 8, count = 0;
    for (size_t i = 0; i < message->msg_iovlen && remaining; i++) {
        parts[count] = message->msg_iov[i];
        if (parts[count].iov_len > remaining) parts[count].iov_len = remaining;
        remaining -= parts[count++].iov_len;
    }
    struct msghdr short_message = {.msg_iov = parts, .msg_iovlen = count};
    ssize_t result = sendmsg(fd, &short_message, flags);
    assert(result == 8);
    paused = true;
    pthread_cond_broadcast(&changed);
    while (!resume_write) pthread_cond_wait(&changed, &barrier);
    pthread_mutex_unlock(&barrier);
    return result;
}

static const unsigned char video_frame[20] = {'$', 0, 0, 16, 0x80, 96};
static const unsigned char audio_frame[20] = {'$', 2, 0, 16, 0x80, 0};
static const char response[] = "RTSP/1.0 200 OK\r\nCSeq: 7\r\nContent-Length: 0\r\n\r\n";

struct operation {
    struct c300x_rtsp_writer *writer;
    int fd;
    int kind; /* 0 video, 1 response, 2 audio */
    bool fails;
};

static void *write_operation(void *argument)
{
    struct operation *operation = argument;
    if (operation->kind == 1) {
        send_rtsp_response(operation->writer, operation->fd, 200, "7", NULL, NULL);
    } else {
        const unsigned char *frame = operation->kind == 2 ? audio_frame : video_frame;
        ssize_t result = c300x_rtsp_send_interleaved(
            operation->writer, operation->fd, frame[1], frame + 4, 16
        );
        assert(operation->fails ? result < 0 : result == 20);
    }
    return NULL;
}

static size_t expected(unsigned char *out, int kind)
{
    size_t size = kind == 1 ? sizeof(response) - 1 : sizeof(video_frame);
    const void *data = kind == 1 ? (const void *)response
        : (kind == 2 ? audio_frame : video_frame);
    memcpy(out, data, size);
    return size;
}

static void serialization_test(int first_kind, int second_kind)
{
    int pair[2], independent[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, independent) == 0);
    struct c300x_rtsp_writer *writer = c300x_rtsp_writer_create();
    struct c300x_rtsp_writer *other = c300x_rtsp_writer_create();
    assert(writer && other);
    int retained_fd = dup(pair[0]);
    assert(retained_fd >= 0);
    short_fd = pair[0];
    observed_mutex = &writer->mutex;
    struct operation first = {writer, pair[0], first_kind, false};
    struct operation second = {writer, retained_fd, second_kind, false};
    pthread_t a, b;
    assert(pthread_create(&a, NULL, write_operation, &first) == 0);
    pthread_mutex_lock(&barrier);
    while (!paused) pthread_cond_wait(&changed, &barrier);
    pthread_mutex_unlock(&barrier);
    assert(pthread_create(&b, NULL, write_operation, &second) == 0);
    pthread_mutex_lock(&barrier);
    while (!contender_seen) pthread_cond_wait(&changed, &barrier);
    pthread_mutex_unlock(&barrier);

    /* This completes while the first connection remains paused inside sendmsg. */
    struct operation independent_write = {other, independent[0], 0, false};
    write_operation(&independent_write);
    unsigned char received[256], wanted[256];
    assert(recv(independent[1], received, sizeof(received), MSG_DONTWAIT) == 20);
    assert(memcmp(received, video_frame, 20) == 0);
    pthread_mutex_lock(&barrier);
    resume_write = true;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&barrier);
    assert(pthread_join(a, NULL) == 0);
    assert(pthread_join(b, NULL) == 0);
    size_t size = expected(wanted, first_kind);
    size += expected(wanted + size, second_kind);
    assert(recv(pair[1], received, size, MSG_WAITALL) == (ssize_t)size);
    assert(memcmp(received, wanted, size) == 0);
    c300x_rtsp_writer_release(writer);
    c300x_rtsp_writer_release(other);
    close(retained_fd);
    close(pair[0]); close(pair[1]);
    close(independent[0]); close(independent[1]);
}

static void framing_test(void)
{
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    struct c300x_rtsp_writer *writer = c300x_rtsp_writer_create();
    assert(writer);
    unsigned char packet[513], received[517];
    for (size_t i = 0; i < sizeof(packet); i++) packet[i] = (unsigned char)i;
    assert(c300x_rtsp_send_interleaved(writer, pair[0], 254, packet, sizeof(packet)) == 517);
    assert(recv(pair[1], received, sizeof(received), MSG_WAITALL) == 517);
    const unsigned char header[] = {'$', 254, 2, 1};
    const size_t header_len = sizeof(header);
    assert(memcmp(received, header, header_len) == 0);
    assert(memcmp(&received[header_len], packet, sizeof(packet)) == 0);
    /* The helper borrows both resources; a subsequent write must still work. */
    assert(c300x_rtsp_send_interleaved(writer, pair[0], 2, packet, 1) == 5);
    assert(recv(pair[1], received, 5, MSG_WAITALL) == 5);
    assert(memcmp(received, (unsigned char[]){'$', 2, 0, 1, 0}, 5) == 0);
    c300x_rtsp_writer_release(writer);
    close(pair[0]); close(pair[1]);
}

static void timeout_test(void)
{
    int pair[2];
    unsigned char byte;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    struct c300x_rtsp_writer *writer = c300x_rtsp_writer_create();
    assert(writer);
    pthread_mutex_lock(&writer->mutex);
    /* A frame that cannot start is dropped; the connection stays open. */
    long long start = c300x_monotonic_ms();
    assert(c300x_rtsp_send_interleaved(writer, pair[0], 0, video_frame + 4, 16) == 0);
    long long elapsed = c300x_monotonic_ms() - start;
    assert(elapsed >= 250 && elapsed < 1000);
    assert(recv(pair[1], &byte, 1, MSG_DONTWAIT) < 0 && errno == EAGAIN);
    /* While it stays stalled, frames are dropped without a wait. */
    start = c300x_monotonic_ms();
    assert(c300x_rtsp_send_interleaved(writer, pair[0], 0, video_frame + 4, 16) == 0);
    assert(c300x_monotonic_ms() - start < 100);
    /* A response that cannot be written closes the connection. */
    start = c300x_monotonic_ms();
    struct operation response_write = {writer, pair[0], 1, true};
    write_operation(&response_write);
    elapsed = c300x_monotonic_ms() - start;
    assert(elapsed >= 2000 && elapsed < 2750);
    assert(recv(pair[1], &byte, 1, MSG_DONTWAIT) == 0);
    pthread_mutex_unlock(&writer->mutex);
    c300x_rtsp_writer_release(writer);
    close(pair[0]); close(pair[1]);
}

static void fill(int fd)
{
    int small = 4096;
    unsigned char padding[4096] = {0};
    assert(setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &small, sizeof(small)) == 0);
    while (send(fd, padding, sizeof(padding), MSG_DONTWAIT | MSG_NOSIGNAL) > 0) {}
}

static size_t drain(int fd)
{
    unsigned char buffer[4096];
    size_t total = 0;
    ssize_t n;
    while ((n = recv(fd, buffer, sizeof(buffer), MSG_DONTWAIT)) > 0) total += (size_t)n;
    return total;
}

static void slow_reader_test(void)
{
    /* A client that reads late, as over WiFi, loses frames, not its session. */
    int pair[2];
    unsigned char received[20];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    fill(pair[0]);
    struct c300x_rtsp_writer *writer = c300x_rtsp_writer_create();
    assert(writer);
    assert(c300x_rtsp_send_interleaved(writer, pair[0], 0, video_frame + 4, 16) == 0);
    assert(atomic_load(&writer->stalled_since) != 0);
    assert(drain(pair[1]) > 0);
    assert(c300x_rtsp_send_interleaved(writer, pair[0], 0, video_frame + 4, 16) == 20);
    assert(atomic_load(&writer->stalled_since) == 0);
    assert(recv(pair[1], received, sizeof(received), MSG_WAITALL) == 20);
    assert(memcmp(received, video_frame, 20) == 0);
    c300x_rtsp_writer_release(writer);
    close(pair[0]); close(pair[1]);
}

static void stall_limit_test(void)
{
    /* A client that has taken no frame for the stall limit is closed. */
    int pair[2];
    unsigned char byte;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    fill(pair[0]);
    struct c300x_rtsp_writer *writer = c300x_rtsp_writer_create();
    assert(writer);
    assert(c300x_rtsp_send_interleaved(writer, pair[0], 0, video_frame + 4, 16) == 0);
    atomic_store(&writer->stalled_since, c300x_monotonic_ms() - RTSP_STALL_LIMIT_MS + 1000);
    assert(c300x_rtsp_send_interleaved(writer, pair[0], 0, video_frame + 4, 16) == 0);
    atomic_store(&writer->stalled_since, c300x_monotonic_ms() - RTSP_STALL_LIMIT_MS);
    assert(c300x_rtsp_send_interleaved(writer, pair[0], 0, video_frame + 4, 16) < 0);
    (void)drain(pair[1]);
    assert(recv(pair[1], &byte, 1, MSG_DONTWAIT) == 0);
    c300x_rtsp_writer_release(writer);
    close(pair[0]); close(pair[1]);
}

static void partial_failure_test(void)
{
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    struct c300x_rtsp_writer *writer = c300x_rtsp_writer_create();
    assert(writer);
    short_fd = pair[0];
    resume_write = fail_remainder = true;
    struct operation operation = {writer, pair[0], 0, true};
    write_operation(&operation);
    short_fd = -1;
    send_rtsp_response(writer, pair[0], 200, "7", NULL, NULL);
    unsigned char received[64];
    assert(recv(pair[1], received, sizeof(received), 0) == 8);
    assert(memcmp(received, video_frame, 8) == 0);
    assert(recv(pair[1], received, sizeof(received), MSG_DONTWAIT) == 0);
    c300x_rtsp_writer_release(writer);
    close(pair[0]); close(pair[1]);
}

struct slow_read {
    int fd;
    size_t want;
    unsigned char *received;
};

static void *read_after_pause(void *arg)
{
    struct slow_read *reader = arg;
    assert(recv(reader->fd, reader->received, reader->want, MSG_WAITALL) == (ssize_t)reader->want);
    return NULL;
}

static void real_partial_recovery(void)
{
    /* Real kernel backpressure, without replacing sendmsg or advancing a
     * fake clock: a small socket cannot fit this one interleaved packet. */
    int pair[2], small = 4096;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(setsockopt(pair[0], SOL_SOCKET, SO_SNDBUF, &small, sizeof(small)) == 0);
    struct c300x_rtsp_writer *writer = c300x_rtsp_writer_create();
    assert(writer);
    unsigned char payload[48000], got[4 + sizeof(payload) + sizeof(response) - 1];
    for (size_t i = 0; i < sizeof(payload); i++) payload[i] = (unsigned char)(i * 7);
    assert(c300x_rtsp_send_interleaved(writer, pair[0], 2, payload, sizeof(payload)) == 0);
    assert(writer->tail_len > 0 && writer->tail_len < sizeof(payload));
    memset(payload, 0, sizeof(payload));
    struct slow_read reader = {pair[1], sizeof(got), got};
    pthread_t thread;
    assert(pthread_create(&thread, NULL, read_after_pause, &reader) == 0);
    send_rtsp_response(writer, pair[0], 200, "7", NULL, NULL);
    assert(pthread_join(thread, NULL) == 0);
    assert(memcmp(got, (unsigned char[]){'$', 2, 0xbb, 0x80}, 4) == 0);
    for (size_t i = 0; i < sizeof(payload); i++) assert(got[4 + i] == (unsigned char)(i * 7));
    const size_t response_at = 4 + sizeof(payload);
    assert(memcmp(&got[response_at], response, sizeof(response) - 1) == 0);
    c300x_rtsp_writer_release(writer);
    close(pair[0]); close(pair[1]);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (strcmp(argv[1], "response_after_rtp") == 0) serialization_test(0, 1);
    else if (strcmp(argv[1], "rtp_after_response") == 0) serialization_test(1, 0);
    else if (strcmp(argv[1], "audio_after_video") == 0) serialization_test(0, 2);
    else if (strcmp(argv[1], "framing") == 0) framing_test();
    else if (strcmp(argv[1], "timeouts") == 0) timeout_test();
    else if (strcmp(argv[1], "partial_failure") == 0) partial_failure_test();
    else if (strcmp(argv[1], "real_partial_recovery") == 0) real_partial_recovery();
    else if (strcmp(argv[1], "slow_reader") == 0) slow_reader_test();
    else if (strcmp(argv[1], "stall_limit") == 0) stall_limit_test();
    else assert(!"unknown case");
    return 0;
}
