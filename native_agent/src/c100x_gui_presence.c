#include "c100x_gui_presence.h"
#include "device_detect.h"
#include "http_auth.h"
#include "http_util.h"
#include "time_util.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>

static int error(int fd, int status, const char *code)
{
    char body[128];
    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}\n", code);
    c300x_http_send_json(fd, status, "GUI Presence", body);
    return 1;
}

void c100x_gui_presence_init(struct c100x_gui_presence *state)
{
    memset(state, 0, sizeof(*state));
    state->fd = -1;
    state->blocked = 1;
}

void c100x_gui_presence_close(struct c100x_gui_presence *state)
{
    if (state->fd >= 0) close_agent_socket(state->fd);
    c100x_gui_presence_init(state);
}

static int connected(const struct c100x_gui_presence *state)
{
    char byte;
    if (state->fd < 0 || c300x_monotonic_ms() >= state->deadline_ms) return 0;
    /* EOF and unexpected pipelined data both revoke the lease immediately. */
    int result = recv(state->fd, &byte, 1, MSG_PEEK | MSG_DONTWAIT);
    return result < 0 && (errno == EAGAIN || errno == EWOULDBLOCK);
}

int c100x_gui_presence_prepare(struct c100x_gui_presence *state, struct pollfd *fd)
{
    *fd = (struct pollfd){.fd = state->fd, .events = POLLIN};
    if (state->fd < 0) return -1;
    long long remaining = state->deadline_ms - c300x_monotonic_ms();
    return remaining > 0 ? (int)remaining : 0;
}

void c100x_gui_presence_tick(struct c100x_gui_presence *state, const struct pollfd *fd)
{
    if (state->fd < 0) return;
    if (fd->revents || !connected(state)) {
        if (!fd->revents && c300x_monotonic_ms() >= state->deadline_ms)
            c300x_http_send_json(state->fd, 200, "OK", "{\"ok\":true,\"renew\":true}\n");
        c100x_gui_presence_close(state);
    }
}

static int valid_generation(const char *value)
{
    return strlen(value) == 64 && strspn(value, "0123456789abcdef") == 64;
}

int c100x_gui_presence_route(struct c100x_gui_presence *state, int fd,
    const struct request *request, int loopback)
{
    char header[32], generation[128], blocked[8], body[256];
    if (c300x_device_model() != C300X_DEVICE_MODEL_C100X)
        return error(fd, 404, "c100x_required");
    if (!loopback || header_value(request, "origin", header, sizeof(header))
        || !header_value(request, "x-c100x-gui", header, sizeof(header))
        || strcmp(header, "presence-v1")) return error(fd, 403, "gui_header_required");
    if (strcmp(request->method, "GET")) return error(fd, 405, "method_not_allowed");
    query_param_value(request->query, "generation", generation, sizeof(generation));
    if (!valid_generation(generation)) return error(fd, 400, "invalid_generation");
    if (!connected(state)) c100x_gui_presence_close(state);
    if (!strcmp(request->path, "/ui/c100x/presence/status")) {
        int ready = state->fd >= 0 && !strcmp(state->generation, generation);
        snprintf(body, sizeof(body),
            "{\"ok\":true,\"gui_ready\":%s,\"idle\":%s,\"installation_verified\":false}\n",
            ready ? "true" : "false", ready && !state->blocked ? "true" : "false");
        c300x_http_send_json(fd, 200, "OK", body);
        return 1;
    }
    if (strcmp(request->path, "/ui/c100x/presence/next")) return error(fd, 404, "not_found");
    query_param_value(request->query, "blocked", blocked, sizeof(blocked));
    if (strcmp(blocked, "0") && strcmp(blocked, "1")) return error(fd, 400, "invalid_guard");
    if (state->fd >= 0) return error(fd, 409, "gui_already_connected");
    memcpy(state->generation, generation, 65);
    state->blocked = blocked[0] == '1';
    state->deadline_ms = c300x_monotonic_ms() + 60000;
    state->fd = fd;
    return 0;
}
