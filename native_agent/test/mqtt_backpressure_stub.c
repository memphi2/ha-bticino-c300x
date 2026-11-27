/* Test-only short writes and small kernel buffer, limited to the loopback broker.
 * Backpressure is from the kernel; poll and HTTP sockets are not mocked. */
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

#include "../src/mqtt_output.h"

int __real_connect(int, const struct sockaddr *, socklen_t);
ssize_t __real_send(int, const void *, size_t, int);
int __real_poll(struct pollfd *, nfds_t, int);
int __real___poll_chk(struct pollfd *, nfds_t, int, size_t);

static void *shutdown_from_worker(void *unused)
{
    (void)unused;
    (void)raise(SIGTERM);
    return NULL;
}

/* Inject after the loop tested its stop flag, before entering the kernel. */
static void inject_shutdown(int timeout)
{
    if (timeout < 0 || timeout > 1000) {
        if (unlink("shutdown-before-poll") == 0) {
            fprintf(stderr, "shutdown injected on main thread before poll\n");
            (void)raise(SIGTERM);
        } else if (unlink("shutdown-worker-before-poll") == 0) {
            pthread_t worker;
            if (pthread_create(&worker, NULL, shutdown_from_worker, NULL) == 0) {
                (void)pthread_join(worker, NULL);
                fprintf(stderr, "shutdown injected on worker thread before poll\n");
            }
        }
    }
}

int __wrap_poll(struct pollfd *fds, nfds_t count, int timeout)
{
    inject_shutdown(timeout);
    return __real_poll(fds, count, timeout);
}

/* Ubuntu's fortified headers route the main loop through this entry point. */
int __wrap___poll_chk(struct pollfd *fds, nfds_t count, int timeout, size_t bytes)
{
    inject_shutdown(timeout);
    return __real___poll_chk(fds, count, timeout, bytes);
}

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

/* The agent drops a broker that took nothing for 500 ms. A test on a busy
 * machine needs longer between filling the socket and reading it again, so
 * the agent's write timeout is seen 30 s later here. */
int __real_c300x_mqtt_output_timeout(const struct c300x_mqtt_output *output, long long now);
int __wrap_c300x_mqtt_output_timeout(const struct c300x_mqtt_output *output, long long now)
{
    return __real_c300x_mqtt_output_timeout(output, now - 30000);
}
