#include "http_util.h"

#include <string.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

static int hex_digit_value(char ch)
{
    if (ch >= '0' && ch <= '9') {
        return ch - '0';
    }
    if (ch >= 'a' && ch <= 'f') {
        return ch - 'a' + 10;
    }
    if (ch >= 'A' && ch <= 'F') {
        return ch - 'A' + 10;
    }
    return -1;
}

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

void percent_decode_query_value(
    const char *value_start,
    const char *value_end,
    char *out,
    size_t out_len
)
{
    size_t written = 0;

    if (out_len == 0) {
        return;
    }
    while (value_start < value_end && written + 1 < out_len) {
        if (*value_start == '%' && value_start + 2 < value_end) {
            int high = hex_digit_value(value_start[1]);
            int low = hex_digit_value(value_start[2]);

            if (high >= 0 && low >= 0) {
                out[written++] = (char)((high << 4) | low);
                value_start += 3;
                continue;
            }
        }
        out[written++] = *value_start == '+' ? ' ' : *value_start;
        value_start++;
    }
    out[written] = '\0';
}

int query_param_value(const char *query, const char *key, char *out, size_t out_len)
{
    const char *ptr;
    size_t key_len;

    if (out_len > 0) {
        out[0] = '\0';
    }
    if (query == NULL || key == NULL || out_len == 0) {
        return 0;
    }
    key_len = strlen(key);
    if (key_len == 0) {
        return 0;
    }
    ptr = query;
    while (*ptr != '\0') {
        const char *value_start;
        const char *pair_end;

        while (*ptr == '&') {
            ptr++;
        }
        if (*ptr == '\0') {
            break;
        }
        pair_end = strchr(ptr, '&');
        if (pair_end == NULL) {
            pair_end = ptr + strlen(ptr);
        }
        if (strncmp(ptr, key, key_len) == 0 && ptr[key_len] == '=') {
            value_start = ptr + key_len + 1;
            percent_decode_query_value(value_start, pair_end, out, out_len);
            return 1;
        }
        ptr = pair_end;
        if (*ptr == '&') {
            ptr++;
        }
    }
    return 0;
}

int validate_action_id(const char *value)
{
    size_t index;
    size_t len;

    if (value == NULL) {
        return 0;
    }
    len = strlen(value);
    if (len == 0 || len > 80) {
        return 0;
    }
    for (index = 0; index < len; index++) {
        unsigned char ch = (unsigned char)value[index];

        if (
            (ch >= 'a' && ch <= 'z')
            || (ch >= 'A' && ch <= 'Z')
            || (ch >= '0' && ch <= '9')
            || ch == '_' || ch == '.' || ch == ':' || ch == '-'
        ) {
            continue;
        }
        return 0;
    }
    return 1;
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

void close_agent_socket(int fd)
{
    if (fd < 0) {
        return;
    }
    (void)shutdown(fd, SHUT_RDWR);
    close(fd);
}
