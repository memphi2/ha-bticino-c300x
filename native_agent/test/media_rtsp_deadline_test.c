/* Deterministic deadline checks against the production writer. */
#include <assert.h>
#include <errno.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

static ssize_t deadline_sendmsg(int, const struct msghdr *, int);
static long long deadline_now(void);
#define sendmsg deadline_sendmsg
#define c300x_monotonic_ms deadline_now
#include "../src/media_rtsp_io.c"
#undef c300x_monotonic_ms
#undef sendmsg

enum injection { INTERRUPT, PARTIAL_INTERRUPT, SHORT_WRITES };
static enum injection injection;
static long long now = 1000;
static unsigned int writes;

static long long deadline_now(void)
{
    return now;
}

static ssize_t deadline_sendmsg(int fd, const struct msghdr *message, int flags)
{
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

int main(int argc, char **argv)
{
    assert(argc == 2);
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
    long long budget = response ? RTSP_RESPONSE_MS
        : (injection == INTERRUPT ? RTSP_FRAME_START_MS : RTSP_FRAME_FINISH_MS);
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
