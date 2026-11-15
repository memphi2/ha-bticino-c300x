#ifndef C300X_HTTP_UTIL_H
#define C300X_HTTP_UTIL_H

#include <netinet/in.h>

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
int send_all_bytes(int fd, const char *payload, size_t payload_len);
void set_fd_nonblocking(int fd);
void set_fd_cloexec(int fd);
void allow_socket_reuse(int fd);
void close_agent_socket(int fd);
void c300x_http_send_json(int client_fd, int status, const char *reason, const char *body);
/* True for a loopback source or one of this host's own IPv4 addresses. The
 * device's event frames on the UDP event port are sent by its own services. */
int c300x_udp_source_is_local(const struct sockaddr_in *source);

/* Main-loop HTTP responses only; outbound clients retain send_all_bytes().
 * close_agent_socket() transfers a queued response's fd to the output queue. */
#define C300X_HTTP_MAX_OUTPUTS 8
#define C300X_HTTP_OUTPUT_LIMIT (512 * 1024)
/* Preserve the former eight-times-64-KiB total despite larger memo lists. */
#define C300X_HTTP_OUTPUT_QUEUE_LIMIT (512 * 1024)
#define C300X_HTTP_OUTPUT_TIMEOUT_MS 2000
int c300x_http_write(int fd, const char *data, size_t size);
int c300x_http_outputs_prepare(struct pollfd *fds);
void c300x_http_outputs_handle(const struct pollfd *fds);
void c300x_http_outputs_close(void);

#endif
