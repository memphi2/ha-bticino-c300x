#include "http_util.h"

#include <string.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/time.h>

int parse_http_url(
    const char *url,
    char *host,
    size_t host_len,
    char *port,
    size_t port_len,
    char *path,
    size_t path_len
)
{
    const char *ptr;
    const char *host_start;
    const char *host_end;
    const char *path_start;
    const char *colon;
    const char *bracket_end;

    if (strncmp(url, "http://", 7) != 0) {
        return 0;
    }
    host_start = url + 7;
    path_start = strchr(host_start, '/');
    if (path_start == NULL) {
        path_start = url + strlen(url);
    }
    colon = NULL;
    if (*host_start == '[') {
        bracket_end = memchr(host_start, ']', (size_t)(path_start - host_start));
        if (bracket_end == NULL || bracket_end == host_start + 1) {
            return 0;
        }
        if (bracket_end + 1 < path_start) {
            if (bracket_end[1] != ':') {
                return 0;
            }
            colon = bracket_end + 1;
        }
        host_start++;
        host_end = bracket_end;
    } else {
        for (ptr = host_start; ptr < path_start; ptr++) {
            if (*ptr == ':') {
                colon = ptr;
                break;
            }
        }
        host_end = colon != NULL ? colon : path_start;
    }
    if (host_end == host_start || (size_t)(host_end - host_start) >= host_len) {
        return 0;
    }
    memcpy(host, host_start, (size_t)(host_end - host_start));
    host[host_end - host_start] = '\0';
    if (colon != NULL) {
        size_t len = (size_t)(path_start - colon - 1);
        if (len == 0 || len >= port_len) {
            return 0;
        }
        memcpy(port, colon + 1, len);
        port[len] = '\0';
    } else {
        snprintf(port, port_len, "80");
    }
    if (*path_start == '\0') {
        snprintf(path, path_len, "/");
    } else {
        snprintf(path, path_len, "%s", path_start);
    }
    return 1;
}

void http_host_header_value(
    const char *host,
    const char *port,
    char *out,
    size_t out_len
)
{
    int is_ipv6_literal = strchr(host, ':') != NULL;
    int default_port = strcmp(port, "80") == 0;

    if (is_ipv6_literal) {
        if (default_port) {
            snprintf(out, out_len, "[%s]", host);
        } else {
            snprintf(out, out_len, "[%s]:%s", host, port);
        }
    } else if (default_port) {
        snprintf(out, out_len, "%s", host);
    } else {
        snprintf(out, out_len, "%s:%s", host, port);
    }
}

void set_socket_timeout(int fd, int timeout_ms)
{
    struct timeval timeout;
    timeout.tv_sec = timeout_ms / 1000;
    timeout.tv_usec = (timeout_ms % 1000) * 1000;
    (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
}

void set_fd_nonblocking(int fd)
{
    int enabled = 1;

    (void)ioctl(fd, FIONBIO, &enabled);
}

void set_fd_cloexec(int fd)
{
    (void)ioctl(fd, FIOCLEX);
}

void allow_socket_reuse(int fd)
{
    int enabled = 1;

    (void)setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &enabled, sizeof(enabled));
}
