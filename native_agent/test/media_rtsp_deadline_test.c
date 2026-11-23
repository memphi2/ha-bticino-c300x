/* Deterministic deadline checks against the production writer. */
#include <assert.h>
#include <errno.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

static ssize_t deadline_sendmsg(int, const struct msghdr *, int);
static int deadline_poll(struct pollfd *, nfds_t, int);
static long long deadline_now(void);
#define sendmsg deadline_sendmsg
#define poll deadline_poll
#define c300x_monotonic_ms deadline_now
#include "../src/media_rtsp_io.c"
#undef c300x_monotonic_ms
#undef sendmsg
#undef poll

enum injection { INTERRUPT, PARTIAL_INTERRUPT, SHORT_WRITES, PARTIAL_STALL };
static enum injection injection;
static long long now = 1000;
static unsigned int writes;
static int stalled_fd = -1;
static size_t allowance;
static int broken;

static long long deadline_now(void)
{
    return now;
}

static ssize_t deadline_sendmsg(int fd, const struct msghdr *message, int flags)
{
    if (injection == PARTIAL_STALL) {
        if (fd != stalled_fd) return sendmsg(fd, message, flags);
        if (broken) { errno = EPIPE; return -1; }
        if (allowance) {
            struct iovec parts[2];
            struct msghdr part = *message;
            size_t left = allowance;
            assert(message->msg_iovlen <= 2);
            part.msg_iov = parts;
            part.msg_iovlen = 0;
            for (size_t i = 0; i < message->msg_iovlen && left; i++) {
                parts[i] = message->msg_iov[i];
                if (parts[i].iov_len > left) parts[i].iov_len = left;
                left -= parts[i].iov_len;
                part.msg_iovlen++;
            }
            ssize_t sent = sendmsg(fd, &part, flags);
            if (sent > 0) allowance -= (size_t)sent;
            return sent;
        }
        errno = EAGAIN;
        return -1;
    }
    writes++;
    now += 50;
    if (writes <= 100 && (injection == INTERRUPT ||
        (injection == PARTIAL_INTERRUPT && writes > 1))) {
        errno = EINTR;
        return -1;
    }
    if (injection != INTERRUPT) {
        struct iovec byte = {.iov_base = message->msg_iov[0].iov_base, .iov_len = 1};
        struct msghdr part = {.msg_iov = &byte, .msg_iovlen = 1};
        return sendmsg(fd, &part, flags);
    }
    return sendmsg(fd, message, flags);
}

static int deadline_poll(struct pollfd *fds, nfds_t count, int timeout)
{
    if (injection == PARTIAL_STALL && count == 1 && fds[0].fd == stalled_fd) {
        now += timeout;
        return 0;
    }
    return poll(fds, count, timeout);
}

static void expect_bytes(int fd, const void *expected, size_t length)
{
    unsigned char received[1304];
    assert(length <= sizeof(received));
    assert(recv(fd, received, length, MSG_DONTWAIT) == (ssize_t)length);
    assert(memcmp(received, expected, length) == 0);
}

static void expect_open_empty(int fd)
{
    unsigned char byte;
    assert(recv(fd, &byte, 1, MSG_DONTWAIT) < 0 && errno == EAGAIN);
}

static void fanout(struct c300x_rtsp_writer *a, int slow,
                   struct c300x_rtsp_writer *b, int healthy,
                   const unsigned char *packet, size_t length)
{
    rtsp_send_target_t targets[] = {
        {.writer = a, .fd = dup(slow), .transport_tcp = true},
        {.writer = b, .fd = dup(healthy), .transport_tcp = true},
    };
    assert(targets[0].fd >= 0 && targets[1].fd >= 0);
    stalled_fd = targets[0].fd;
    c300x_rtsp_writer_retain(a);
    c300x_rtsp_writer_retain(b);
    c300x_rtsp_send_targets(targets, 2, packet, length);
}

static void partial_stall(const char *kind)
{
    int slow[2], healthy[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, slow) == 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, healthy) == 0);
    struct c300x_rtsp_writer *a = c300x_rtsp_writer_create();
    struct c300x_rtsp_writer *b = c300x_rtsp_writer_create();
    assert(a && b);
    unsigned char original[1304] = {'$', 4, 5, 20}, buffer[1304];
    for (size_t i = 4; i < sizeof(original); i++) original[i] = (unsigned char)(i * 31 + i / 256);
    memcpy(buffer, original, sizeof(buffer));
    injection = PARTIAL_STALL;
    stalled_fd = slow[0];
    allowance = 693;
    long long start = now;
    assert(writer_send(a, slow[0], buffer, 4, buffer + 4, 1300, RTSP_FRAME) == 0);
    assert(now - start == 250);
    expect_bytes(slow[1], original, 693);
    expect_open_empty(slow[1]);
    memset(buffer, 0xcc, sizeof(buffer)); /* The relay immediately reuses its input. */
    long long deferred = now;
    for (unsigned char i = 1; i <= 3; i++) {
        unsigned char frame[] = {'$', 0, 0, 2, i, 0x55};
        fanout(a, slow[0], b, healthy[0], frame + 4, 2);
        expect_bytes(healthy[1], frame, sizeof(frame));
        expect_open_empty(slow[1]);
        assert(now == deferred);
    }

    stalled_fd = slow[0];
    unsigned char next[] = {'$', 2, 0, 3, 0xff, 0xfe, 0xfd};
    if (strcmp(kind, "stall_limit") == 0 || strcmp(kind, "epipe") == 0) {
        if (strcmp(kind, "epipe") == 0) broken = 1;
        else {
            now = start + 4999;
            assert(writer_send(a, slow[0], next, sizeof(next), NULL, 0, RTSP_FRAME) == 0);
            expect_open_empty(slow[1]);
            now = deferred + 5000;
        }
        assert(writer_send(a, slow[0], next, sizeof(next), NULL, 0, RTSP_FRAME) < 0);
        assert(recv(slow[1], buffer, 1, MSG_DONTWAIT) == 0);
    } else if (strcmp(kind, "recover_fanout") == 0) {
        /* Each retry finishes the previous frame and starts (but cannot
         * finish) the current one. Neither step may spend a new poll budget. */
        size_t left = sizeof(original) - 693;
        const unsigned char *tail = original + 693;
        unsigned char previous[3];
        for (unsigned char i = 1; i <= 4; i++) {
            unsigned char frame[] = {'$', 0, 0, 3, i, 0xab, 0xcd};
            allowance = left + 4;
            fanout(a, slow[0], b, healthy[0], frame + 4, 3);
            assert(now == deferred);
            expect_bytes(healthy[1], frame, sizeof(frame));
            expect_bytes(slow[1], tail, left);
            expect_bytes(slow[1], frame, 4);
            expect_open_empty(slow[1]);
            memcpy(previous, frame + 4, sizeof(previous));
            tail = previous;
            left = sizeof(previous);
        }
    } else {
        /* Another partial flush advances the tail, but drops this new input. */
        allowance = 17;
        assert(writer_send(a, slow[0], next, sizeof(next), NULL, 0, RTSP_FRAME) == 0);
        expect_bytes(slow[1], original + 693, 17);
        expect_open_empty(slow[1]);
        allowance = 4096;
        if (strcmp(kind, "response") == 0) {
            const char response[] = "RTSP/1.0 200 OK\r\nCSeq: 9\r\nContent-Length: 2\r\n\r\nOK";
            c300x_rtsp_writer_end_media(a);
            assert(writer_send(a, slow[0], next, sizeof(next), NULL, 0, RTSP_FRAME) == 0);
            expect_open_empty(slow[1]);
            send_rtsp_response(a, slow[0], 200, "9", NULL, "OK");
            expect_bytes(slow[1], original + 710, sizeof(original) - 710);
            expect_bytes(slow[1], response, sizeof(response) - 1);
        } else {
            next[6] = 0x42;
            assert(writer_send(a, slow[0], next, 4, next + 4, 3, RTSP_FRAME) == 7);
            expect_bytes(slow[1], original + 710, sizeof(original) - 710);
            expect_bytes(slow[1], next, sizeof(next));
        }
        expect_open_empty(slow[1]);
    }
    c300x_rtsp_writer_release(a);
    c300x_rtsp_writer_release(b);
    close(slow[0]); close(slow[1]);
    close(healthy[0]); close(healthy[1]);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (strncmp(argv[1], "partial_stall_", 14) == 0) {
        partial_stall(argv[1] + 14);
        return 0;
    }
    int response = strcmp(argv[1], "response_interrupt") == 0;
    injection = strcmp(argv[1], "short_writes") == 0 ? SHORT_WRITES
        : (strcmp(argv[1], "partial_interrupt") == 0 ? PARTIAL_INTERRUPT : INTERRUPT);
    int sockets[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    struct c300x_rtsp_writer *writer = c300x_rtsp_writer_create();
    assert(writer);
    unsigned char packet[256] = {0};
    long long start = now;
    ssize_t result = writer_send(writer, sockets[0], packet, sizeof(packet), NULL, 0,
                                 response ? RTSP_RESPONSE : RTSP_FRAME);
    long long budget = response ? RTSP_RESPONSE_MS : RTSP_FRAME_WRITE_MS;
    assert(now - start <= budget);
    if (injection == INTERRUPT && !response) {
        assert(result == 0);
        assert(recv(sockets[1], packet, sizeof(packet), MSG_DONTWAIT) < 0 && errno == EAGAIN);
    } else if (response) {
        assert(result < 0);
        assert(recv(sockets[1], packet, sizeof(packet), MSG_DONTWAIT) == 0);
    } else {
        assert(result == 0);
        ssize_t prefix = recv(sockets[1], packet, sizeof(packet), MSG_DONTWAIT);
        assert(prefix > 0 && prefix < (ssize_t)sizeof(packet));
        expect_open_empty(sockets[1]);
    }
    c300x_rtsp_writer_release(writer);
    close(sockets[0]);
    close(sockets[1]);
    return 0;
}
