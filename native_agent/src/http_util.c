#include "http_util.h"

#include <string.h>
#include <stdio.h>
#include <ctype.h>
#include <errno.h>
#include <ifaddrs.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

struct http_output {
    int fd;
    int close_pending;
    char *data;
    size_t size;
    size_t sent;
    /* Without progress until `deadline`, or unfinished at `limit`, it ends. */
    long long deadline;
    long long limit;
};

/* Only the agent event loop sends HTTP responses and owns these slots. */
static struct http_output outputs[C300X_HTTP_MAX_OUTPUTS];

static long long output_now(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        return 0;
    }
    return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static void clear_output(struct http_output *output, int failed)
{
    if (failed || output->close_pending) {
        (void)shutdown(output->fd, SHUT_RDWR);
    }
    if (output->close_pending) {
        close(output->fd);
    }
    free(output->data);
    memset(output, 0, sizeof(*output));
}

int c300x_http_write(int fd, const char *data, size_t size)
{
    struct http_output *slot = NULL;
    size_t queued = 0;
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS; i++) {
        queued += outputs[i].size;
    }
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS; i++) {
        struct http_output *output = &outputs[i];
        if (output->data != NULL && output->fd == fd) {
            if (size > C300X_HTTP_OUTPUT_LIMIT - output->size
                || size > C300X_HTTP_OUTPUT_QUEUE_LIMIT - queued) {
                clear_output(output, 1);
                return 0;
            }
            char *grown = realloc(output->data, output->size + size);
            if (grown == NULL) {
                clear_output(output, 1);
                return 0;
            }
            memcpy(grown + output->size, data, size);
            output->data = grown;
            output->size += size;
            return 1;
        }
        if (output->data == NULL && slot == NULL) {
            slot = output;
        }
    }
    if (size == 0) {
        return 1;
    }
    if (size > C300X_HTTP_OUTPUT_LIMIT) {
        (void)shutdown(fd, SHUT_RDWR);
        return 0;
    }
    ssize_t sent = send(fd, data, size, MSG_NOSIGNAL | MSG_DONTWAIT);
    if (sent == (ssize_t)size) {
        return 1;
    }
    if (sent < 0 && errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) {
        (void)shutdown(fd, SHUT_RDWR);
        return 0;
    }
    size_t used = sent > 0 ? (size_t)sent : 0;
    if (size - used > C300X_HTTP_OUTPUT_QUEUE_LIMIT - queued) {
        (void)shutdown(fd, SHUT_RDWR);
        return 0;
    }
    char *pending = slot != NULL ? malloc(size - used) : NULL;
    if (pending == NULL) {
        (void)shutdown(fd, SHUT_RDWR);
        return 0;
    }
    memcpy(pending, data + used, size - used);
    long long queued_at = output_now();
    *slot = (struct http_output){.fd = fd, .data = pending,
        .size = size - used, .deadline = queued_at + C300X_HTTP_OUTPUT_TIMEOUT_MS,
        .limit = queued_at + C300X_HTTP_OUTPUT_TOTAL_TIMEOUT_MS};
    return 1;
}

int c300x_http_outputs_prepare(struct pollfd *fds)
{
    int timeout = -1;
    long long now = output_now();
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS; i++) {
        struct http_output *output = &outputs[i];
        fds[i] = (struct pollfd){.fd = output->data != NULL ? output->fd : -1,
            .events = POLLOUT};
        if (output->data != NULL) {
            int remaining = output->deadline > now ? (int)(output->deadline - now) : 0;
            if (timeout < 0 || remaining < timeout) {
                timeout = remaining;
            }
        }
    }
    return timeout;
}

void c300x_http_outputs_handle(const struct pollfd *fds)
{
    long long now = output_now();
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS; i++) {
        struct http_output *output = &outputs[i];
        if (output->data == NULL) {
            continue;
        }
        if (output->deadline <= now) {
            clear_output(output, 1);
            continue;
        }
        if (fds[i].fd != output->fd || !fds[i].revents) {
            continue;
        }
        if (fds[i].revents & (POLLERR | POLLHUP | POLLNVAL)) {
            clear_output(output, 1);
            continue;
        }
        ssize_t sent = send(output->fd, output->data + output->sent,
            output->size - output->sent, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (sent < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) {
            continue;
        }
        if (sent <= 0) {
            clear_output(output, 1);
            continue;
        }
        output->sent += (size_t)sent;
        output->deadline = now + C300X_HTTP_OUTPUT_TIMEOUT_MS;
        if (output->deadline > output->limit) {
            output->deadline = output->limit;
        }
        if (output->sent == output->size) {
            clear_output(output, 0);
        }
    }
}

void c300x_http_outputs_close(void)
{
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS; i++) {
        if (outputs[i].data != NULL) {
            outputs[i].close_pending = 1;
            clear_output(&outputs[i], 1);
        }
    }
}

int send_all_bytes(int fd, const char *payload, size_t payload_len)
{
    size_t sent = 0;

    while (sent < payload_len) {
        ssize_t written = send(fd, payload + sent, payload_len - sent, MSG_NOSIGNAL);
        if (written < 0 && errno == EINTR) {
            continue;
        }
        if (written <= 0) {
            return 0;
        }
        sent += (size_t)written;
    }
    return 1;
}

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
    int https = strncmp(url, "https://", 8) == 0;

    if (!https && strncmp(url, "http://", 7) != 0) {
        return 0;
    }
    for (ptr = url; *ptr; ptr++) {
        if (iscntrl((unsigned char)*ptr) || isspace((unsigned char)*ptr) || *ptr == '#') {
            return 0;
        }
    }
    host_start = url + (https ? 8 : 7);
    path_start = strchr(host_start, '/');
    if (path_start == NULL) {
        path_start = url + strlen(url);
    }
    if (memchr(host_start, '@', (size_t)(path_start - host_start)) != NULL
        || memchr(host_start, '?', (size_t)(path_start - host_start)) != NULL
        || strlen(path_start) >= path_len) {
        return 0;
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
        for (ptr = port; *ptr; ptr++) {
            if (!isdigit((unsigned char)*ptr)) {
                return 0;
            }
        }
        char *port_end;
        unsigned long port_number = strtoul(port, &port_end, 10);
        if (*port_end != '\0' || port_number == 0 || port_number > 65535) {
            return 0;
        }
    } else {
        if (snprintf(port, port_len, "%s", https ? "443" : "80") >= (int)port_len) {
            return 0;
        }
    }
    if (*path_start == '\0') {
        if (snprintf(path, path_len, "/") >= (int)path_len) {
            return 0;
        }
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
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS; i++) {
        if (outputs[i].data != NULL && outputs[i].fd == fd) {
            outputs[i].close_pending = 1;
            return;
        }
    }
    (void)shutdown(fd, SHUT_RDWR);
    close(fd);
}

void c300x_http_send_json(int client_fd, int status, const char *reason, const char *body)
{
    char header[1024];
    size_t body_len = strlen(body);
    int header_len = snprintf(
        header,
        sizeof(header),
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %zu\r\n"
        "Connection: close\r\n"
        "\r\n",
        status,
        reason,
        body_len
    );

    if (header_len <= 0 || (size_t)header_len >= sizeof(header)
        || !c300x_http_write(client_fd, header, (size_t)header_len)) {
        return;
    }
    (void)c300x_http_write(client_fd, body, body_len);
}

int c300x_udp_source_is_local(const struct sockaddr_in *source)
{
    struct ifaddrs *addresses = NULL;
    int local = 0;

    if (source == NULL || source->sin_family != AF_INET) {
        return 0;
    }
    if ((ntohl(source->sin_addr.s_addr) >> 24) == 127) {
        return 1;
    }
    if (getifaddrs(&addresses) != 0) {
        return 0;
    }
    for (struct ifaddrs *item = addresses; item != NULL && !local; item = item->ifa_next) {
        const struct sockaddr_in *own = (const struct sockaddr_in *)item->ifa_addr;
        local = own != NULL && own->sin_family == AF_INET
            && own->sin_addr.s_addr == source->sin_addr.s_addr;
    }
    freeifaddrs(addresses);
    return local;
}
