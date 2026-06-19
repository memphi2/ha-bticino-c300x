#ifndef C300X_HTTP_UTIL_H
#define C300X_HTTP_UTIL_H

#include <poll.h>
#include <stddef.h>

#ifndef POLLRDHUP
#define POLLRDHUP 0
#endif

#define C300X_SOCKET_CLOSED_REVENTS (POLLERR | POLLHUP | POLLNVAL | POLLRDHUP)

int parse_http_url(
    const char *url,
    char *host,
    size_t host_len,
    char *port,
    size_t port_len,
    char *path,
    size_t path_len
);
void http_host_header_value(
    const char *host,
    const char *port,
    char *out,
    size_t out_len
);
void percent_decode_query_value(
    const char *value_start,
    const char *value_end,
    char *out,
    size_t out_len
);
int query_param_value(const char *query, const char *key, char *out, size_t out_len);
int validate_action_id(const char *value);
void set_socket_timeout(int fd, int timeout_ms);
void set_fd_nonblocking(int fd);
void set_fd_cloexec(int fd);
void allow_socket_reuse(int fd);
void close_agent_socket(int fd);

#endif
