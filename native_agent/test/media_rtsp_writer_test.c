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
    assert(memcmp(received, header, sizeof(header)) == 0);
    assert(memcmp(received + sizeof(header), packet, sizeof(packet)) == 0);
    /* The helper borrows both resources; a subsequent write must still work. */
    assert(c300x_rtsp_send_interleaved(writer, pair[0], 2, packet, 1) == 5);
    assert(recv(pair[1], received, 5, MSG_WAITALL) == 5);
    assert(memcmp(received, (unsigned char[]){'$', 2, 0, 1, 0}, 5) == 0);
    c300x_rtsp_writer_release(writer);
    close(pair[0]); close(pair[1]);
}

static void timeout_test(void)
{
    for (int response_write = 0; response_write < 2; response_write++) {
        int pair[2];
        assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
        struct c300x_rtsp_writer *writer = c300x_rtsp_writer_create();
        assert(writer);
        pthread_mutex_lock(&writer->mutex);
        long long start = c300x_monotonic_ms();
        struct operation operation = {writer, pair[0], response_write, true};
        write_operation(&operation);
        long long elapsed = c300x_monotonic_ms() - start;
        int budget = response_write ? 2000 : 250;
        assert(elapsed >= budget && elapsed < budget + 750);
        unsigned char byte;
        assert(recv(pair[1], &byte, 1, MSG_DONTWAIT) == 0);
        pthread_mutex_unlock(&writer->mutex);
        c300x_rtsp_writer_release(writer);
        close(pair[0]); close(pair[1]);
    }
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

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (strcmp(argv[1], "response_after_rtp") == 0) serialization_test(0, 1);
    else if (strcmp(argv[1], "rtp_after_response") == 0) serialization_test(1, 0);
    else if (strcmp(argv[1], "audio_after_video") == 0) serialization_test(0, 2);
    else if (strcmp(argv[1], "framing") == 0) framing_test();
    else if (strcmp(argv[1], "timeouts") == 0) timeout_test();
    else if (strcmp(argv[1], "partial_failure") == 0) partial_failure_test();
    else assert(!"unknown case");
    return 0;
}
