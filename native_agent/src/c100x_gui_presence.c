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

static int random_probe(char out[33])
{
    unsigned char bytes[16];
    FILE *file = fopen("/dev/urandom", "rb");
    if (!file) return 0;
    size_t count = fread(bytes, 1, sizeof(bytes), file);
    fclose(file);
    if (count != sizeof(bytes)) return 0;
    for (size_t i = 0; i < sizeof(bytes); i++) snprintf(out + i * 2, 3, "%02x", bytes[i]);
    return 1;
}

static int valid_probe(const char *value)
{
    return strlen(value) == 32 && strspn(value, "0123456789abcdef") == 32;
}

int c100x_gui_presence_route(struct c100x_gui_presence *state, int fd,
    const struct request *request, int loopback)
{
    char header[32], generation[128], probe[64], blocked[8], body[384];
    if (c300x_device_model() != C300X_DEVICE_MODEL_C100X)
        return error(fd, 404, "c100x_required");
    if (!loopback || header_value(request, "origin", header, sizeof(header))
        || !header_value(request, "x-c100x-gui", header, sizeof(header))
        || strcmp(header, "presence-v1")) return error(fd, 403, "gui_header_required");
    if (strcmp(request->method, "GET")) return error(fd, 405, "method_not_allowed");
    query_param_value(request->query, "generation", generation, sizeof(generation));
    if (!valid_generation(generation)) return error(fd, 400, "invalid_generation");
    if (state->fd >= 0 && !connected(state)) c100x_gui_presence_close(state);
    query_param_value(request->query, "probe", probe, sizeof(probe));
    if (probe[0] && !valid_probe(probe)) return error(fd, 400, "invalid_probe");
    if (!strcmp(request->path, "/ui/c100x/presence/probe")) {
        char challenge[33];
        if (state->fd < 0 || strcmp(state->generation, generation)) return error(fd, 409, "gui_unavailable");
        if (!random_probe(challenge)) return error(fd, 503, "entropy_unavailable");
        snprintf(body, sizeof(body), "{\"ok\":true,\"probe\":\"%s\"}\n", challenge);
        c300x_http_send_json(state->fd, 200, "OK", body);
        c100x_gui_presence_close(state);
        memcpy(state->generation, generation, 65);
        memcpy(state->probe, challenge, 33);
        state->probe_deadline_ms = c300x_monotonic_ms() + 2000;
        c300x_http_send_json(fd, 200, "OK", body);
        return 1;
    }
    if (!strcmp(request->path, "/ui/c100x/presence/status")) {
        int present = state->fd >= 0 && !strcmp(state->generation, generation);
        int ready = present && state->proved && valid_probe(probe) && !strcmp(probe, state->probe)
            && c300x_monotonic_ms() < state->probe_deadline_ms;
        snprintf(body, sizeof(body),
            "{\"ok\":true,\"gui_ready\":%s,\"idle\":%s,\"present\":%s,"
            "\"generation\":\"%s\",\"probe\":\"%s\",\"installation_verified\":false}\n",
            ready ? "true" : "false", ready && !state->blocked ? "true" : "false",
            present ? "true" : "false", generation, probe);
        c300x_http_send_json(fd, 200, "OK", body);
        return 1;
    }
    if (strcmp(request->path, "/ui/c100x/presence/next")) return error(fd, 404, "not_found");
    query_param_value(request->query, "blocked", blocked, sizeof(blocked));
    if (strcmp(blocked, "0") && strcmp(blocked, "1")) return error(fd, 400, "invalid_guard");
    if (state->fd >= 0) return error(fd, 409, "gui_already_connected");
    state->proved = valid_probe(probe) && !strcmp(state->probe, probe)
        && !strcmp(state->generation, generation) && c300x_monotonic_ms() < state->probe_deadline_ms;
    memcpy(state->generation, generation, 65);
    state->blocked = blocked[0] == '1';
    state->deadline_ms = c300x_monotonic_ms() + 60000;
    state->fd = fd;
    return 0;
}
