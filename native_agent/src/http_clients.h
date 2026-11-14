#ifndef C300X_HTTP_CLIENTS_H
#define C300X_HTTP_CLIENTS_H

#include "http_request.h"

#define C300X_HTTP_MAX_CLIENTS 8
#define C300X_HTTP_KIND_API 1
#define C300X_HTTP_KIND_UI 2
/* Slots only the loopback-bound UI listener may take, so a flood of idle LAN
 * connections to the API cannot lock the display out. */
#define C300X_HTTP_UI_RESERVED_SLOTS 2

struct c300x_http_client {
    int fd;
    int kind;
    long long deadline;
    size_t used;
    char *buffer;
};

struct c300x_http_clients {
    struct c300x_http_client slots[C300X_HTTP_MAX_CLIENTS];
};

typedef void (*c300x_http_ready_fn)(int fd, int kind, char *buffer, void *context);
void c300x_http_clients_init(struct c300x_http_clients *clients);
int c300x_http_clients_add(struct c300x_http_clients *clients, int fd, int kind, long long now);
int c300x_http_clients_prepare(struct c300x_http_clients *clients, struct pollfd *fds, long long now);
void c300x_http_clients_handle(struct c300x_http_clients *clients, const struct pollfd *fds, c300x_http_ready_fn ready, void *context);
void c300x_http_clients_close(struct c300x_http_clients *clients);

#endif
