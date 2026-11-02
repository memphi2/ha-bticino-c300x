#include "../src/http_clients.h"
#include "../src/http_util.c"
#include "../src/system_metrics.h"
#include <assert.h>

static int completed;
static void ready(int fd, int kind, char *buffer, void *context)
{
    (void)context;
    assert(kind == 2);
    assert(strstr(buffer, "GET /health ") != NULL);
    completed++;
    close(fd);
}

int main(void)
{
    struct c300x_http_clients clients;
    struct pollfd fds[C300X_HTTP_MAX_CLIENTS];
    c300x_http_clients_init(&clients);
    long long now = c300x_system_metrics_monotonic_ms();
    assert(c300x_http_clients_prepare(&clients, fds, now) == -1);
    int slow[2], fast[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, slow) == 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, fast) == 0);
    assert(c300x_http_clients_add(&clients, slow[0], 1, now));
    assert(c300x_http_clients_add(&clients, fast[0], 2, now));
    const char *request = "GET /health HTTP/1.1\r\nHost: local\r\n\r\n";
    assert(send_all_bytes(fast[1], request, strlen(request)));
    assert(c300x_http_clients_prepare(&clients, fds, now) == C300X_HTTP_REQUEST_TIMEOUT_MS);
    assert(poll(fds, C300X_HTTP_MAX_CLIENTS, 0) == 1);
    c300x_http_clients_handle(&clients, fds, ready, NULL);
    assert(completed == 1);
    assert(c300x_system_metrics_monotonic_ms() - now < 100);
    clients.slots[0].deadline = now - 1;
    c300x_http_clients_handle(&clients, fds, ready, NULL);
    assert(clients.slots[0].fd == -1);
    close(slow[1]);
    close(fast[1]);
    int peers[C300X_HTTP_MAX_CLIENTS];
    for (int i = 0; i < C300X_HTTP_MAX_CLIENTS; i++) {
        int pair[2];
        assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
        assert(c300x_http_clients_add(&clients, pair[0], 1, now));
        peers[i] = pair[1];
    }
    assert(!c300x_http_clients_add(&clients, -1, 1, now));
    c300x_http_clients_close(&clients);
    for (int i = 0; i < C300X_HTTP_MAX_CLIENTS; i++) {
        char byte;
        assert(recv(peers[i], &byte, 1, 0) == 0);
        close(peers[i]);
    }
    return 0;
}
