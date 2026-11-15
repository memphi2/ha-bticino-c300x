#include "display_callback.h"
#include "http_util.h"
#include "https_client.h"
#include "time_util.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <netdb.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static int display_wait(int fd, short events, long long deadline)
{
    for (;;) {
        long long remaining = deadline - c300x_monotonic_ms();
        if (remaining <= 0) { errno = ETIMEDOUT; return 0; }
        struct pollfd pending = {.fd = fd, .events = events};
        int ready = poll(&pending, 1, remaining > INT_MAX ? INT_MAX : (int)remaining);
        if (ready < 0 && errno == EINTR) continue;
        /* HUP/ERR must reach recv/getsockopt so EOF and connect failure are
         * distinguished. Every retry still consumes the original deadline. */
        return ready > 0 && !(pending.revents & POLLNVAL);
    }
}

static int display_connect(int fd, const struct addrinfo *address, long long deadline)
{
    int flags = fcntl(fd, F_GETFL);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0
        || c300x_monotonic_ms() >= deadline) return 0;
    if (connect(fd, address->ai_addr, address->ai_addrlen) == 0) return 1;
    if (errno != EINPROGRESS && errno != EINTR) return 0;
    if (!display_wait(fd, POLLOUT, deadline)) return 0;
    int error = 0;
    socklen_t length = sizeof(error);
    return getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &length) == 0 && error == 0;
}

static int display_send(int fd, const char *data, size_t size, long long deadline)
{
    while (size > 0) {
        if (!display_wait(fd, POLLOUT, deadline)) return 0;
        ssize_t sent = send(fd, data, size, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (sent < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) continue;
        if (sent <= 0) return 0;
        data += sent;
        size -= (size_t)sent;
    }
    return 1;
}

int c300x_display_post(
    const char *webhook_url,
    const char *shared_secret,
    int timeout_ms,
    const char *body,
    char *response,
    size_t response_len
)
{
    char host[256];
    char host_header[288];
    char port[16];
    char path[256];
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    struct addrinfo *item;
    int fd = -1;
    char header[1024];
    int ok = 0;
    ssize_t receive_result = -1;

    if (response_len > 0) {
        response[0] = '\0';
    }
    if (webhook_url[0] == '\0' || timeout_ms <= 0) {
        return 0;
    }
    if (!parse_http_url(
        webhook_url,
        host,
        sizeof(host),
        port,
        sizeof(port),
        path,
        sizeof(path)
    )) {
        return 0;
    }

    if (strncmp(webhook_url, "https://", 8) == 0) {
        long status;
        const char *error;
        ok = c300x_https_post(
            webhook_url, "X-Bticino-C300X-Secret", shared_secret, body,
            response, response_len, timeout_ms,
            &status, &error
        );
        if (ok) {
            if (response_len > 0 && response[0] == '\0') {
                snprintf(response, response_len, "{}\n");
            }
        }
        return ok;
    }

    /* The platform resolver is synchronous; time spent there also consumes
     * the budget, but cannot be interrupted by socket deadlines. */
    long long deadline = c300x_monotonic_ms() + timeout_ms;
    memset(&hints, 0, sizeof(hints));
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_family = AF_UNSPEC;
    if (getaddrinfo(host, port, &hints, &result) != 0) {
        return 0;
    }
    http_host_header_value(host, port, host_header, sizeof(host_header));
    for (item = result; item != NULL; item = item->ai_next) {
        if (c300x_monotonic_ms() >= deadline) break;
        fd = socket(item->ai_family, item->ai_socktype, item->ai_protocol);
        if (fd < 0) {
            continue;
        }
        set_fd_cloexec(fd);
        if (display_connect(fd, item, deadline)) {
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(result);
    if (fd < 0) {
        return 0;
    }

    snprintf(
        header,
        sizeof(header),
        "POST %s HTTP/1.1\r\n"
        "Host: %s\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %zu\r\n"
        "%s%s%s"
        "Connection: close\r\n"
        "\r\n",
        path,
        host_header,
        strlen(body),
        shared_secret[0] != '\0' ? "X-Bticino-C300X-Secret: " : "",
        shared_secret[0] != '\0' ? shared_secret : "",
        shared_secret[0] != '\0' ? "\r\n" : ""
    );

    if (display_send(fd, header, strlen(header), deadline)
        && display_send(fd, body, strlen(body), deadline)) {
        size_t received = 0;
        while (received + 1 < response_len) {
            if (!display_wait(fd, POLLIN, deadline)) {
                receive_result = -1;
                break;
            }
            receive_result = recv(fd, response + received, response_len - received - 1, MSG_DONTWAIT);
            if (receive_result < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) {
                continue;
            }
            if (receive_result <= 0) {
                break;
            }
            received += (size_t)receive_result;
        }
        if (received > 0) {
            response[received] = '\0';
        }
    }
    close(fd);

    if (response_len > 0 && receive_result == 0) {
        const char *status_end = strstr(response, "\r\n");
        const char *separator = strstr(response, "\r\n\r\n");
        if (status_end != NULL && separator != NULL) {
            size_t status_len = (size_t)(status_end - response);
            if (
                status_len >= 13
                && (strncmp(response, "HTTP/1.1 2", 10) == 0 || strncmp(response, "HTTP/1.0 2", 10) == 0)
                && isdigit((unsigned char)response[10])
                && isdigit((unsigned char)response[11])
                && response[12] == ' '
            ) {
                ok = 1;
            }
        }
        if (ok) {
            if (separator != NULL) {
                const char *body = separator + 4;
                size_t body_len = strlen(body);
                if (body_len >= response_len) {
                    body_len = response_len - 1;
                }
                memmove(response, body, body_len);
                response[body_len] = '\0';
            }
            if (response[0] == '\0') {
                snprintf(response, response_len, "{}\n");
            }
        }
    }

    return ok;
}
