#include "http_clients.h"
#include "http_util.h"
#include "system_metrics.h"
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

static void clear_client(struct c300x_http_client *client)
{
    if (client->fd >= 0) {
        close_agent_socket(client->fd);
    }
    free(client->buffer);
    memset(client, 0, sizeof(*client));
    client->fd = -1;
}

void c300x_http_clients_init(struct c300x_http_clients *clients)
{
    memset(clients, 0, sizeof(*clients));
    for (int i = 0; i < C300X_HTTP_MAX_CLIENTS; i++) {
        clients->slots[i].fd = -1;
    }
}

int c300x_http_clients_add(struct c300x_http_clients *clients, int fd, int kind, long long now)
{
    for (int i = 0; i < C300X_HTTP_MAX_CLIENTS; i++) {
        struct c300x_http_client *client = &clients->slots[i];
        if (client->fd >= 0) {
            continue;
        }
        client->buffer = malloc(REQUEST_BUFFER_SIZE);
        if (client->buffer == NULL) {
            return 0;
        }
        client->fd = fd;
        client->kind = kind;
        client->used = 0;
        client->deadline = now + C300X_HTTP_REQUEST_TIMEOUT_MS;
        set_socket_timeout(fd, 2000);
        return 1;
    }
    return 0;
}

int c300x_http_clients_prepare(struct c300x_http_clients *clients, struct pollfd *fds, long long now)
{
    int timeout = -1;
    for (int i = 0; i < C300X_HTTP_MAX_CLIENTS; i++) {
        struct c300x_http_client *client = &clients->slots[i];
        fds[i] = (struct pollfd){.fd = client->fd, .events = POLLIN};
        if (client->fd < 0) {
            continue;
        }
        long long remaining = client->deadline - now;
        int wait = remaining > 0 ? (int)remaining : 0;
        if (timeout < 0 || wait < timeout) {
            timeout = wait;
        }
    }
    return timeout;
}

void c300x_http_clients_handle(struct c300x_http_clients *clients, const struct pollfd *fds, c300x_http_ready_fn ready, void *context)
{
    for (int i = 0; i < C300X_HTTP_MAX_CLIENTS; i++) {
        struct c300x_http_client *client = &clients->slots[i];
        if (client->fd < 0) {
            continue;
        }
        if (client->deadline <= c300x_system_metrics_monotonic_ms()) {
            clear_client(client);
            continue;
        }
        if (fds[i].fd != client->fd || !fds[i].revents) {
            continue;
        }
        ssize_t received = recv(client->fd, client->buffer + client->used,
            REQUEST_BUFFER_SIZE - client->used - 1, MSG_DONTWAIT);
        if (received < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) {
            continue;
        }
        if (received <= 0) {
            clear_client(client);
            continue;
        }
        client->used += (size_t)received;
        int size_error;
        int status = c300x_http_request_status(client->buffer, client->used, REQUEST_BUFFER_SIZE, &size_error);
        if (status == 0) {
            continue;
        }
        if (status > 0) {
            int fd = client->fd;
            client->fd = -1;
            ready(fd, client->kind, client->buffer, context);
        } else {
            c300x_http_send_json(client->fd, size_error > 0 ? 413 : 400,
                size_error > 0 ? "Payload Too Large" : "Bad Request", "{\"ok\":false,\"error\":\"invalid_request\"}\n");
        }
        clear_client(client);
    }
}

void c300x_http_clients_close(struct c300x_http_clients *clients)
{
    for (int i = 0; i < C300X_HTTP_MAX_CLIENTS; i++) {
        clear_client(&clients->slots[i]);
    }
}
