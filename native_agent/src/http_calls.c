#include "http_calls.h"

#include <stdio.h>
#include <string.h>

#include "c300x_agent.h"
#include "http_media_actions.h"
#include "http_util.h"
#include "json_util.h"
#include "openwebnet_call.h"
#include "string_util.h"
#include "time_util.h"
#include "video_control.h"

#define CALLS_PREFIX "/api/v1/calls/"
#define UNITS_PREFIX "/api/v1/outdoor-units/"

void c300x_call_hub_init(struct c300x_call_hub *hub, const struct c300x_config *config,
                         c300x_call_emit_fn emit, void *context)
{
    memset(hub, 0, sizeof(*hub));
    hub->config = config;
    hub->sink = (struct c300x_call_sink){emit, context, &hub->units};
}

static void load_units(struct c300x_call_hub *hub)
{
    hub->sink.units = &hub->units;
    if (hub->config != NULL) {
        c300x_outdoor_units_load(&hub->units, C300X_ARCHIVE_XML_PATH, C300X_CONF_XML_PATH,
                                 hub->config->video_sip_devaddr, hub->config->lock_address);
    } else if (!hub->units.loaded) {
        c300x_outdoor_units_build(&hub->units, NULL, "missing", NULL, "20", "20");
    }
}

void c300x_call_hub_frame(struct c300x_call_hub *hub, const char *frame)
{
    if (hub == NULL || frame == NULL || strncmp(frame, "*8*", 3) != 0) {
        return;
    }
    if (!hub->units.loaded) {
        load_units(hub);
    }
    c300x_calls_frame(&hub->calls, &hub->sink, frame, c300x_monotonic_ms());
}

/* data with ,"unit":...,"call_id":... added before its closing brace. */
static int decorate(const char *data, const char *unit, const char *call_id, char *out, size_t out_len)
{
    size_t length = strlen(data);
    size_t used = 0;

    if (length < 2 || data[length - 1] != '}' || strstr(data, "\"unit\"") != NULL) {
        return 1;
    }
    out[0] = '\0';
    if (!c300x_appendf(out, out_len, &used, "%.*s%s\"unit\":\"%s\",\"call_id\":%s%s%s}",
                       (int)(length - 1), data, length > 2 ? "," : "", unit,
                       call_id ? "\"" : "null", call_id ? call_id : "", call_id ? "\"" : "")) {
        return 1;
    }
    return 2;
}

int c300x_call_hub_event(struct c300x_call_hub *hub, const char *type, const char *data,
                         char *out, size_t out_len)
{
    long long now = c300x_monotonic_ms();
    char text[C300X_UNIT_WHERE_LEN * 2];

    if (hub == NULL || type == NULL || data == NULL) {
        return 1;
    }
    if (!hub->units.loaded) {
        load_units(hub);
    }
    if (strcmp(type, "doorbell.pressed") == 0) {
        if (strstr(data, "\"call_id\"") != NULL) {
            return 1;
        }
        c300x_json_string_field(data, "raw", text, sizeof(text));
        return c300x_calls_ring(&hub->calls, &hub->sink, text, now, out, out_len) ? 2 : 0;
    }
    if (strcmp(type, "doorbell.media.closed") == 0) {
        c300x_calls_media_closed(&hub->calls, &hub->sink, now);
        return 1;
    }
    if (strcmp(type, "door_unlock.started") == 0 || strcmp(type, "door_unlock.ended") == 0) {
        c300x_json_string_field(data, "address", text, sizeof(text));
        int index = c300x_outdoor_units_find_lock(&hub->units, text);
        if (index < 0) {
            return 1;
        }
        const char *unit = hub->units.items[index].id;
        const struct c300x_call *call = c300x_calls_live_for_unit(&hub->calls, unit);
        return decorate(data, unit, call ? call->id : NULL, out, out_len);
    }
    if (strcmp(type, "doorbell.view_requested") == 0) {
        const struct c300x_call *call = c300x_calls_current(&hub->calls);
        for (int index = 0; call == NULL && index < hub->units.count; index++) {
            const struct c300x_call *view = c300x_calls_live_for_unit(&hub->calls, hub->units.items[index].id);
            call = view != NULL && view->view ? view : NULL;
        }
        return call != NULL && call->unit[0] != '\0' ? decorate(data, call->unit, call->id, out, out_len) : 1;
    }
    return 1;
}

int c300x_call_hub_timeout_ms(struct c300x_call_hub *hub)
{
    return c300x_calls_timeout_ms(&hub->calls, c300x_monotonic_ms());
}

void c300x_call_hub_tick(struct c300x_call_hub *hub)
{
    if (c300x_calls_timeout_ms(&hub->calls, c300x_monotonic_ms()) == 0) {
        c300x_calls_tick(&hub->calls, &hub->sink, c300x_monotonic_ms());
    }
}

static void send_not_current(int client_fd, const struct c300x_calls *calls)
{
    const struct c300x_call *current = c300x_calls_current(calls);
    char body[160];

    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"call_not_current\",\"current_call_id\":%s%s%s}\n",
             current ? "\"" : "null", current ? current->id : "", current ? "\"" : "");
    c300x_http_send_json(client_fd, 409, "Conflict", body);
}

static void call_action(int client_fd, const struct c300x_call_routes *routes, const struct request *request,
                        const char *call_id, int answer)
{
    struct c300x_call_hub *hub = routes->hub;
    /* Checked before the operation starts, not when its result is answered. */
    int owns = routes->control != NULL && routes->control->worker.owner_fd == client_fd;

    if (!owns) {
        if (!c300x_calls_is_current(&hub->calls, call_id)) {
            send_not_current(client_fd, &hub->calls);
            return;
        }
        if (answer) {
            c300x_calls_answer_started(&hub->calls, call_id);
        }
    }
    if (answer) {
        if (c300x_http_doorbell_call_answer(client_fd, routes->control, routes->video, request)) {
            c300x_calls_answered(&hub->calls, &hub->sink, call_id, "ha", c300x_monotonic_ms());
        }
    } else if (c300x_http_doorbell_call_hangup(client_fd, routes->control, routes->video)) {
        c300x_calls_end(&hub->calls, &hub->sink, call_id, "hangup", c300x_monotonic_ms());
    }
}

/* "current": the current call's unit, else the default one. */
static int unit_index(struct c300x_call_hub *hub, const char *unit_id)
{
    if (strcmp(unit_id, "current") == 0) {
        const struct c300x_call *call = c300x_calls_current(&hub->calls);
        int index = call != NULL ? c300x_outdoor_units_find_id(&hub->units, call->unit) : -1;
        return index >= 0 ? index : hub->units.default_index;
    }
    return c300x_outdoor_units_find_id(&hub->units, unit_id);
}

static void unlock(int client_fd, const struct c300x_call_routes *routes, const struct request *request,
                   const char *unit_id)
{
    struct c300x_call_hub *hub = routes->hub;
    char call_id[C300X_CALL_ID_LEN] = "";
    char press[48], release[48], error[C300X_MAX_ERROR_LEN], body[256];
    char error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];
    int index = unit_index(hub, unit_id);

    if (index < 0) {
        c300x_http_send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"unknown_unit\"}\n");
        return;
    }
    const struct c300x_outdoor_unit *unit = &hub->units.items[index];
    if (c300x_json_string_field_checked(request->body, "call_id", call_id, sizeof(call_id)) < 0) {
        c300x_http_send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_call_id\"}\n");
        return;
    }
    /* Stays true while the request runs again: the call is kept 60 s after its end. */
    if (call_id[0] != '\0'
        && !c300x_calls_unlock_allowed(&hub->calls, call_id, unit->id, c300x_monotonic_ms())) {
        send_not_current(client_fd, &hub->calls);
        return;
    }
    snprintf(press, sizeof(press), "*8*19*%s##", unit->lock_where);
    snprintf(release, sizeof(release), "*8*20*%s##", unit->lock_where);
    if (!c300x_openwebnet_sequence(hub->config, press, hub->config->lock_release_delay_ms, release,
                                   error, sizeof(error))) {
        if (c300x_openwebnet_deferred()) {
            return;
        }
        snprintf(body, sizeof(body), "{\"ok\":false,\"error\":%s}\n",
                 c300x_json_string(error, error_json, sizeof(error_json)));
        c300x_http_send_json(client_fd, 502, "Bad Gateway", body);
        return;
    }
    snprintf(body, sizeof(body), "{\"ok\":true,\"unit\":\"%s\",\"lock_where\":\"%s\",\"call_id\":%s%s%s}\n",
             unit->id, unit->lock_where, call_id[0] ? "\"" : "null", call_id, call_id[0] ? "\"" : "");
    c300x_http_send_json(client_fd, 200, "OK", body);
}

/* The segment of path after prefix up to suffix, which ends the path. */
static int path_segment(const char *path, const char *prefix, const char *suffix, char *out, size_t out_len)
{
    size_t prefix_len = strlen(prefix);
    size_t suffix_len = strlen(suffix);
    size_t length = strlen(path);

    if (strncmp(path, prefix, prefix_len) != 0 || length <= prefix_len + suffix_len
        || strcmp(path + length - suffix_len, suffix) != 0) {
        return 0;
    }
    length -= prefix_len + suffix_len;
    if (length >= out_len || memchr(path + prefix_len, '/', length) != NULL) {
        out[0] = '\0';
        return 1;
    }
    memcpy(out, path + prefix_len, length);
    out[length] = '\0';
    return 1;
}

static void video_activate(int client_fd, const struct c300x_call_routes *routes, const struct request *request)
{
    char unit_id[C300X_UNIT_WHERE_LEN] = "";
    struct c300x_call_hub *hub = routes->hub;
    int checked = c300x_json_string_field_checked(request->body, "unit", unit_id, sizeof(unit_id));
    int index = checked > 0 ? unit_index(hub, unit_id) : hub->units.default_index;
    const struct c300x_call *call = c300x_calls_current(&hub->calls);

    if (checked < 0 || index < 0) {
        c300x_http_send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"unknown_unit\"}\n");
        return;
    }
    /* A ring always shows its caller; on demand only the default unit (phase D). */
    if (index != hub->units.default_index
        && (call == NULL || strcmp(call->unit, hub->units.items[index].id) != 0)) {
        c300x_http_send_json(client_fd, 409, "Conflict", "{\"ok\":false,\"error\":\"unit_video_unsupported\"}\n");
        return;
    }
    c300x_http_doorbell_video_activate(client_fd, routes->control, routes->video, request);
}

int c300x_http_calls_route(int client_fd, const struct c300x_call_routes *routes, const struct request *request)
{
    struct c300x_call_hub *hub = routes->hub;
    char segment[C300X_CALL_ID_LEN + 8];
    char body[4096];
    int get = strcmp(request->method, "GET") == 0;
    int post = strcmp(request->method, "POST") == 0;

    if (strcmp(request->path, "/api/v1/outdoor-units") == 0 && get) {
        load_units(hub);
        if (!c300x_outdoor_units_json(&hub->units, body, sizeof(body))) {
            c300x_copy_string(body, sizeof(body), "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        }
        c300x_http_send_json(client_fd, 200, "OK", body);
        return 1;
    }
    if (strcmp(request->path, "/api/v1/calls") == 0 && get) {
        if (!hub->units.loaded) load_units(hub);
        c300x_calls_tick(&hub->calls, &hub->sink, c300x_monotonic_ms());
        if (!c300x_calls_json(&hub->calls, c300x_monotonic_ms(), body, sizeof(body))) {
            c300x_copy_string(body, sizeof(body), "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        }
        c300x_http_send_json(client_fd, 200, "OK", body);
        return 1;
    }
    if (strcmp(request->path, "/api/v1/video/doorbell/actions/activate") == 0 && post) {
        if (!hub->units.loaded) load_units(hub);
        video_activate(client_fd, routes, request);
        return 1;
    }
    int answer = post && path_segment(request->path, CALLS_PREFIX, "/actions/answer", segment, sizeof(segment));
    int hangup = !answer && post && path_segment(request->path, CALLS_PREFIX, "/actions/hangup", segment, sizeof(segment));
    if (answer || hangup) {
        if (segment[0] == '\0' || strlen(segment) >= C300X_CALL_ID_LEN) {
            c300x_http_send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_call_id\"}\n");
        } else {
            call_action(client_fd, routes, request, segment, answer);
        }
        return 1;
    }
    if (post && path_segment(request->path, UNITS_PREFIX, "/actions/unlock", segment, sizeof(segment))) {
        if (!hub->units.loaded) load_units(hub);
        unlock(client_fd, routes, request, segment);
        return 1;
    }
    return 0;
}
