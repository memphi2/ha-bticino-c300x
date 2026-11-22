#include "../../native_agent/src/c100x_gui_presence.h"
#include "../../native_agent/src/c100x_gui_response.h"
#include "../../native_agent/src/device_detect.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static long long now = 1000;
static int model = C300X_DEVICE_MODEL_C100X, status;
static char response[512];
long long c300x_monotonic_ms(void) { return now; }
enum c300x_device_model c300x_device_model(void) { return model; }
void __wrap_close_agent_socket(int fd) { assert(close(fd) == 0); }
void __wrap_c300x_http_send_json(int fd, int code, const char *reason, const char *body)
{
    (void)fd; (void)reason; status = code;
    snprintf(response, sizeof(response), "%s", body);
}

int main(void)
{
    struct c100x_gui_presence state;
    struct request request = {0};
    struct pollfd pollfd;
    int pair[2];
    c100x_gui_presence_init(&state);
    assert(c100x_gui_presence_prepare(&state, &pollfd) == -1 && pollfd.fd == -1);
    strcpy(request.method, "GET");
    strcpy(request.headers, "X-C100X-GUI: presence-v1\r\n");
    strcpy(request.path, "/ui/c100x/presence/next");
    snprintf(request.query, sizeof(request.query), "generation=%064d&blocked=0", 0);
    model = C300X_DEVICE_MODEL_C300X;
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1 && status == 404);
    model = C300X_DEVICE_MODEL_C100X;
    assert(c100x_gui_presence_route(&state, 99, &request, 0) == 1 && status == 403);
    strcat(request.headers, "Origin: http://foreign\r\n");
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1 && status == 403);
    strcpy(request.headers, "X-C100X-GUI: wrong\r\n");
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1 && status == 403);
    strcpy(request.headers, "X-C100X-GUI: presence-v1\r\n");
    strcpy(request.method, "POST");
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1 && status == 405);
    strcpy(request.method, "GET");
    strcpy(request.query, "generation=../unknown&blocked=0");
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1 && status == 400);
    snprintf(request.query, sizeof(request.query), "generation=%064d&blocked=false", 0);
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1 && status == 400);
    snprintf(request.query, sizeof(request.query), "generation=%064d&blocked=0", 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(c100x_gui_presence_route(&state, pair[0], &request, 1) == 0);
    assert(c100x_gui_presence_prepare(&state, &pollfd) == 60000);
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1 && status == 409);
    strcpy(request.path, "/ui/c100x/presence/status");
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1);
    assert(strstr(response, "\"gui_ready\":false,\"idle\":false,\"present\":true") && strstr(response, "\"installation_verified\":false"));
    /* A live TCP socket can belong to a hung GUI: require a fresh round trip. */
    strcpy(request.path, "/ui/c100x/presence/probe");
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1 && status == 200);
    assert(state.fd == -1 && !state.proved && strlen(state.probe) == 32);
    close(pair[1]);
    char challenge[33], generation[65];
    strcpy(challenge, state.probe);
    snprintf(generation, sizeof(generation), "%064d", 0);
    snprintf(request.query, sizeof(request.query), "generation=%s&blocked=0&probe=%s", generation, challenge);
    strcpy(request.path, "/ui/c100x/presence/status");
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1);
    assert(strstr(response, "\"gui_ready\":false"));
    strcpy(request.path, "/ui/c100x/presence/next");
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(c100x_gui_presence_route(&state, pair[0], &request, 1) == 0 && state.proved);
    strcpy(request.path, "/ui/c100x/presence/status");
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1);
    assert(c100x_gui_readiness_validate(response, generation, challenge));
    assert(!c100x_gui_readiness_validate(response, generation, "bad"));
    now += 2000;
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1);
    assert(!c100x_gui_readiness_validate(response, generation, challenge));
    request.query[11] = 'a';
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1);
    assert(strstr(response, "\"gui_ready\":false"));
    request.query[11] = '0';
    close(pair[1]);
    assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1);
    assert(strstr(response, "\"gui_ready\":false") && state.fd == -1);
    for (int expired = 0; expired <= 1; expired++) {
        strcpy(request.path, "/ui/c100x/presence/next");
        snprintf(request.query, sizeof(request.query), "generation=%064d&blocked=1", 0);
        assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
        assert(c100x_gui_presence_route(&state, pair[0], &request, 1) == 0);
        strcpy(request.path, "/ui/c100x/presence/status");
        assert(c100x_gui_presence_route(&state, 99, &request, 1) == 1);
        assert(strstr(response, "\"gui_ready\":false,\"idle\":false,\"present\":true"));
        c100x_gui_presence_prepare(&state, &pollfd);
        if (expired) now += 60000;
        else assert(write(pair[1], "unexpected", 10) == 10);
        c100x_gui_presence_tick(&state, &pollfd);
        assert(state.fd == -1 && state.generation[0] == '\0');
        if (expired) assert(strstr(response, "\"renew\":true"));
        close(pair[1]);
    }
    c100x_gui_presence_close(&state);
    return 0;
}
