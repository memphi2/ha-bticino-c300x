/* Test-only short writes and small kernel buffer, limited to the loopback broker.
 * Backpressure is from the kernel; poll and HTTP sockets are not mocked. */
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

int __real_connect(int, const struct sockaddr *, socklen_t);
ssize_t __real_send(int, const void *, size_t, int);

static int is_broker(const struct sockaddr *address, socklen_t size)
{
    const char *port = getenv("C300X_TEST_MQTT_PORT");
    if (port == NULL || size < sizeof(struct sockaddr_in) || address->sa_family != AF_INET) {
        return 0;
    }
    const struct sockaddr_in *ipv4 = (const struct sockaddr_in *)address;
    return ipv4->sin_addr.s_addr == htonl(INADDR_LOOPBACK) && ntohs(ipv4->sin_port) == atoi(port);
}

int __wrap_connect(int fd, const struct sockaddr *address, socklen_t size)
{
    if (is_broker(address, size)) {
        int small = 1024, enabled = 1;
        (void)setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &small, sizeof(small));
        (void)setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &enabled, sizeof(enabled));
    }
    return __real_connect(fd, address, size);
}

ssize_t __wrap_send(int fd, const void *buffer, size_t size, int flags)
{
    struct sockaddr_storage peer;
    socklen_t peer_size = sizeof(peer);
    int broker = getpeername(fd, (struct sockaddr *)&peer, &peer_size) == 0
        && is_broker((struct sockaddr *)&peer, peer_size);
    if (broker && size > 31) {
        size = 31;
    }
    ssize_t sent = __real_send(fd, buffer, size, flags);
    int error = errno;
    struct pollfd writable = {.fd = fd, .events = POLLOUT};
    if (broker && ((sent < 0 && (error == EAGAIN || error == EWOULDBLOCK))
        || (sent > 0 && poll(&writable, 1, 0) == 0))) {
        int marker = open("mqtt-backpressure", O_WRONLY | O_CREAT, 0600);
        if (marker >= 0) {
            close(marker);
        }
    }
    errno = error;
    return sent;
}
