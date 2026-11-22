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

static long long deadline_now(void)
{
    return now;
}

static ssize_t deadline_sendmsg(int fd, const struct msghdr *message, int flags)
{
    if (injection == PARTIAL_STALL) {
        if (fd != stalled_fd) return sendmsg(fd, message, flags);
        if (writes++ == 0) {
            struct msghdr header = {.msg_iov = message->msg_iov, .msg_iovlen = 1};
            return sendmsg(fd, &header, flags);
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

static void partial_stall_fanout(void)
{
    int slow[2], healthy[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, slow) == 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, healthy) == 0);
    struct c300x_rtsp_writer *a = c300x_rtsp_writer_create();
    struct c300x_rtsp_writer *b = c300x_rtsp_writer_create();
    assert(a && b);
    rtsp_send_target_t targets[] = {
        {.writer = a, .fd = dup(slow[0]), .transport_tcp = true},
        {.writer = b, .fd = dup(healthy[0]), .transport_tcp = true},
    };
    assert(targets[0].fd >= 0 && targets[1].fd >= 0);
    injection = PARTIAL_STALL;
    stalled_fd = targets[0].fd;
    unsigned char packet[16] = {0}, received[64];
    long long start = now;
    c300x_rtsp_send_targets(targets, 2, packet, sizeof(packet));
    assert(now - start <= 250);
    assert(recv(healthy[1], received, sizeof(received), MSG_DONTWAIT) == 20);
    assert(memcmp(received, (unsigned char[]){'$', 0, 0, 16}, 4) == 0);
    assert(memcmp(received + 4, packet, sizeof(packet)) == 0);
    /* A truncated interleaved message closes only its own connection. */
    assert(recv(slow[1], received, sizeof(received), MSG_DONTWAIT) == 4);
    assert(recv(slow[1], received, sizeof(received), MSG_DONTWAIT) == 0);
    assert(recv(healthy[1], received, sizeof(received), MSG_DONTWAIT) < 0 && errno == EAGAIN);
    close(slow[0]); close(slow[1]);
    close(healthy[0]); close(healthy[1]);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (strcmp(argv[1], "partial_stall_fanout") == 0) {
        partial_stall_fanout();
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
    } else {
        assert(result < 0);
        if (injection != INTERRUPT) {
            ssize_t prefix = recv(sockets[1], packet, sizeof(packet), MSG_DONTWAIT);
            assert(prefix > 0 && prefix < (ssize_t)sizeof(packet));
        }
        assert(recv(sockets[1], packet, sizeof(packet), MSG_DONTWAIT) == 0);
    }
    c300x_rtsp_writer_release(writer);
    close(sockets[0]);
    close(sockets[1]);
    return 0;
}
