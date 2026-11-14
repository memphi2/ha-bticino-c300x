#include "../src/http_clients.h"
#include "../src/http_util.c"
#include "../src/system_metrics.h"
#include <assert.h>

static int completed;
static int delayed_peer = -1;
static const char *delayed_request;
static int delay_handler;
static void ready(int fd, int kind, char *buffer, void *context)
{
    (void)context;
    assert(kind == 2);
    assert(strstr(buffer, "GET /health ") != NULL);
    completed++;
    if (delay_handler) {
        delay_handler = 0;
        if (delayed_peer >= 0) {
            usleep(50000);
            assert(send_all_bytes(delayed_peer, delayed_request, strlen(delayed_request)));
        }
        usleep(600000);
    }
    close(fd);
}

static void expired_ready_test(int late, int complete)
{
    struct c300x_http_clients clients;
    struct pollfd fds[C300X_HTTP_MAX_CLIENTS];
    int first[2], second[2];
    const char *request = "GET /health HTTP/1.1\r\nHost: local\r\n\r\n";
    const char *partial = "GET /health HTTP/1.1\r\nHost: local\r\n";
    c300x_http_clients_init(&clients);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, first) == 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, second) == 0);
    long long now = c300x_system_metrics_monotonic_ms();
    assert(c300x_http_clients_add(&clients, first[0], 2, now));
    assert(c300x_http_clients_add(&clients, second[0], 2, now));
    assert(send_all_bytes(first[1], request, strlen(request)));
    delayed_request = complete ? request : partial;
    delayed_peer = late ? second[1] : -1;
    if (!late) {
        assert(send_all_bytes(second[1], delayed_request, strlen(delayed_request)));
    }
    c300x_http_clients_prepare(&clients, fds, now);
    assert(poll(fds, C300X_HTTP_MAX_CLIENTS, 0) == (late ? 1 : 2));
    int before = completed;
    delay_handler = 1;
    c300x_http_clients_handle(&clients, fds, ready, NULL);
    assert(completed - before == (complete ? 2 : 1));
    assert(clients.slots[1].fd == -1);
    c300x_http_clients_close(&clients);
    close(first[1]);
    close(second[1]);
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
    int api_slots = C300X_HTTP_MAX_CLIENTS - C300X_HTTP_UI_RESERVED_SLOTS;
    for (int i = 0; i < C300X_HTTP_MAX_CLIENTS; i++) {
        int pair[2];
        assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
        int kind = i < api_slots ? C300X_HTTP_KIND_API : C300X_HTTP_KIND_UI;
        if (i == api_slots) {
            int refused[2];
            assert(socketpair(AF_UNIX, SOCK_STREAM, 0, refused) == 0);
            assert(!c300x_http_clients_add(&clients, refused[0], C300X_HTTP_KIND_API, now));
            close(refused[0]);
            close(refused[1]);
        }
        assert(c300x_http_clients_add(&clients, pair[0], kind, now));
        peers[i] = pair[1];
    }
    assert(!c300x_http_clients_add(&clients, -1, C300X_HTTP_KIND_UI, now));
    c300x_http_clients_close(&clients);
    for (int i = 0; i < C300X_HTTP_MAX_CLIENTS; i++) {
        char byte;
        assert(recv(peers[i], &byte, 1, 0) == 0);
        close(peers[i]);
    }
    expired_ready_test(0, 1);
    expired_ready_test(1, 1);
    expired_ready_test(1, 0);
    return 0;
}
