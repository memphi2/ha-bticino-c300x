#include "http_clients.h"
#include "http_client_input.h"
#include "http_util.h"
#include <stdlib.h>
#include <string.h>

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
    if (kind != C300X_HTTP_KIND_UI) {
        int free_slots = 0;
        for (int i = 0; i < C300X_HTTP_MAX_CLIENTS; i++) {
            if (clients->slots[i].fd < 0) {
                free_slots++;
            }
        }
        if (free_slots <= C300X_HTTP_UI_RESERVED_SLOTS) {
            return 0;
        }
    }
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
        fds[i] = (struct pollfd){.fd = client->ready ? -1 : client->fd, .events = POLLIN};
        if (client->fd < 0 || client->ready) {
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
        if (!client->ready) {
            int status = c300x_http_client_receive(client, &fds[i]);
            if (status < 0) {
                clear_client(client);
            }
            if (status <= 0) {
                continue;
            }
            client->ready = 1;
        }
        if (ready(client->fd, client->kind, client->buffer, context)) {
            client->fd = -1;
            clear_client(client);
        }
    }
}

void c300x_http_clients_close(struct c300x_http_clients *clients)
{
    for (int i = 0; i < C300X_HTTP_MAX_CLIENTS; i++) {
        clear_client(&clients->slots[i]);
    }
}
