#include "media_rtsp_io.h"
#include "time_util.h"

#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/uio.h>

ssize_t c300x_rtsp_send_pair(int fd, const void *first, size_t first_len,
                            const void *second, size_t second_len)
{
    struct iovec iov[2];
    struct iovec *pending = iov;
    size_t count = 0, sent = 0;
    long long deadline = c300x_monotonic_ms() + 250;
    if (first_len) iov[count++] = (struct iovec){.iov_base = (void *)first, .iov_len = first_len};
    if (second_len) iov[count++] = (struct iovec){.iov_base = (void *)second, .iov_len = second_len};
    while (count > 0) {
        struct msghdr message = {.msg_iov = pending, .msg_iovlen = count};
        if (!c300x_rtsp_wait_writable(fd, deadline)) return -1;
        ssize_t n = sendmsg(fd, &message, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) continue;
        if (n <= 0) return n;
        sent += (size_t)n;
        size_t advanced = (size_t)n;
        while (count > 0 && advanced >= pending[0].iov_len) {
            advanced -= pending[0].iov_len;
            pending++;
            count--;
        }
        if (count > 0 && advanced > 0) {
            pending[0].iov_base = (char *)pending[0].iov_base + advanced;
            pending[0].iov_len -= advanced;
        }
    }
    return sent == first_len + second_len ? (ssize_t)sent : -1;
}

int parse_client_port(const char *transport)
{
    const char *pos = strstr(transport, "client_port=");
    if (pos == NULL) {
        return 0;
    }
    return atoi(pos + 12);
}

int parse_interleaved_channel(const char *transport)
{
    const char *pos = strstr(transport, "interleaved=");
    if (pos == NULL) {
        return -1;
    }
    return atoi(pos + 12);
}

int c300x_rtsp_connection_add(int fds[RTSP_CONNECTION_LIMIT], int fd)
{
    for (int index = 0; index < RTSP_CONNECTION_LIMIT; index++) {
        if (fds[index] == 0) {
            fds[index] = fd + 1;
            return index;
        }
    }
    return -1;
}

void c300x_rtsp_connections_shutdown(const int fds[RTSP_CONNECTION_LIMIT])
{
    for (int index = 0; index < RTSP_CONNECTION_LIMIT; index++) {
        if (fds[index] > 0) {
            shutdown(fds[index] - 1, SHUT_RDWR);
        }
    }
}

int c300x_rtsp_wait_writable(int fd, long long deadline_ms)
{
    for (;;) {
        long long remaining = deadline_ms - c300x_monotonic_ms();
        if (remaining <= 0) { errno = ETIMEDOUT; return 0; }
        struct pollfd pending = {.fd = fd, .events = POLLOUT};
        int result = poll(&pending, 1, remaining > INT_MAX ? INT_MAX : (int)remaining);
        if (result < 0 && errno == EINTR) continue;
        if (result <= 0) return 0;
        return (pending.revents & (POLLERR | POLLHUP | POLLNVAL)) == 0 &&
               (pending.revents & POLLOUT) != 0;
    }
}

static ssize_t send_all(int fd, const void *buf, size_t len)
{
    const char *p = buf;
    size_t left = len;
    long long deadline = c300x_monotonic_ms() + 2000;
    while (left > 0) {
        if (!c300x_rtsp_wait_writable(fd, deadline)) return -1;
        ssize_t n = send(fd, p, left, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) continue;
        if (n <= 0) {
            return n;
        }
        p += n;
        left -= (size_t)n;
    }
    return (ssize_t)len;
}

void send_rtsp_response(
    int fd,
    int status,
    const char *cseq,
    const char *headers,
    const char *body
) {
    const char *status_text = status == 200 ? "OK" :
        (status == 401 ? "Unauthorized" : (status == 461 ? "Unsupported Transport" : "Error"));
    size_t body_len = body ? strlen(body) : 0;
    char response[4096];
    int n = snprintf(
        response,
        sizeof(response),
        "RTSP/1.0 %d %s\r\n"
        "CSeq: %s\r\n"
        "%s"
        "Content-Length: %zu\r\n"
        "\r\n"
        "%s",
        status,
        status_text,
        cseq && cseq[0] ? cseq : "1",
        headers ? headers : "",
        body_len,
        body ? body : ""
    );
    if (n > 0 && n < (int)sizeof(response)) {
        (void)send_all(fd, response, (size_t)n);
    }
}
