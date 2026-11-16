#include "http_client_input.h"
#include "http_util.h"
#include "system_metrics.h"

#include <errno.h>
#include <sys/socket.h>

int c300x_http_client_receive(struct c300x_http_client *client, const struct pollfd *fd)
{
    /* A previous handler may have delayed a ready socket past its input
     * deadline. Give it one nonblocking read, never another wait. */
    int expired = client->deadline <= c300x_system_metrics_monotonic_ms();
    if (!expired && (fd->fd != client->fd || !fd->revents)) {
        return 0;
    }
    ssize_t received = recv(client->fd, client->buffer + client->used,
        REQUEST_BUFFER_SIZE - client->used - 1, MSG_DONTWAIT);
    if (received < 0 && errno == EINTR) {
        return 0;
    }
    if (received < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
        return expired ? -1 : 0;
    }
    if (received <= 0) {
        return -1;
    }
    client->used += (size_t)received;
    int size_error;
    int status = c300x_http_request_status(client->buffer, client->used, REQUEST_BUFFER_SIZE, &size_error);
    if (status == 0) {
        return client->deadline <= c300x_system_metrics_monotonic_ms() ? -1 : 0;
    }
    if (status > 0) {
        return 1;
    }
    c300x_http_send_json(client->fd, size_error > 0 ? 413 : 400,
        size_error > 0 ? "Payload Too Large" : "Bad Request", "{\"ok\":false,\"error\":\"invalid_request\"}\n");
    return -1;
}
