#include "http_calls.h"

#include <stdio.h>
#include <string.h>

#include "c300x_agent.h"
#include "http_media_actions.h"
#include "http_util.h"
#include "json_util.h"
#include "openwebnet_async.h"
#include "openwebnet_call.h"
#include "string_util.h"
#include "time_util.h"
#include "video_control.h"

#define CALLS_PREFIX "/api/v1/calls/"
/* Well-formed call ids in requests: 1-32 characters (the agent's own are shorter). */
#define REQUEST_CALL_ID_LEN ((int)sizeof(((struct c300x_unlock_resolved *)0)->call_id))
#define UNITS_PREFIX "/api/v1/outdoor-units/"

/* Units the agent saw are written where its configuration is. */
static void seen_path(struct c300x_call_hub *hub, const struct c300x_config *config)
{
    const char *slash = config != NULL ? strrchr(config->config_path, '/') : NULL;

    hub->seen_path[0] = '\0';
    if (slash != NULL && (size_t)(slash - config->config_path) + sizeof("/outdoor-units-seen") < sizeof(hub->seen_path)) {
        snprintf(hub->seen_path, sizeof(hub->seen_path), "%.*s/outdoor-units-seen",
                 (int)(slash - config->config_path), config->config_path);
    }
}

static void hub_emit(void *context, const char *type, const char *data)
{
    struct c300x_call_hub *hub = context;

    if (strcmp(type, "outdoor_units.changed") == 0 && hub->seen_path[0] != '\0') {
        (void)c300x_outdoor_units_save_seen(&hub->units, hub->seen_path);
    }
    if (hub->emit != NULL) {
        hub->emit(hub->context, type, data);
    }
}

void c300x_call_hub_init(struct c300x_call_hub *hub, const struct c300x_config *config,
                         c300x_call_emit_fn emit, void *context)
{
    memset(hub, 0, sizeof(*hub));
    c300x_calls_init(&hub->calls, NULL);
    hub->config = config;
    hub->emit = emit;
    hub->context = context;
    hub->sink = (struct c300x_call_sink){hub_emit, hub, &hub->units};
    seen_path(hub, config);
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
    if (!hub->seen_loaded) {
        hub->seen_loaded = 1;
        c300x_outdoor_units_load_seen(&hub->units, hub->seen_path);
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
        /* The ring answered: on the station (*8*2#1#) or by the agent's own
         * answer (no frame). A view frame (*8*1#5#) opened its view already. */
        c300x_json_string_field(data, "raw", text, sizeof(text));
        if (text[0] == '\0' || strncmp(text, "*8*2#1#", 7) == 0) {
            c300x_calls_answer_seen(&hub->calls, &hub->sink, now);
        }
        const struct c300x_call *call = c300x_calls_current(&hub->calls);
        for (int index = 0; call == NULL && index < hub->units.count; index++) {
            const struct c300x_call *view = c300x_calls_live_for_unit(&hub->calls, hub->units.items[index].id);
            call = view != NULL && view->view ? view : NULL;
        }
        return call != NULL && call->unit[0] != '\0' ? decorate(data, call->unit, call->id, out, out_len) : 1;
    }
    return 1;
}

void c300x_call_hub_media_closed(struct c300x_call_hub *hub, int station_holds_media)
{
    /* The display answered: the agent's ring leg closed, the call goes on
     * until the station's own close. */
    if (hub != NULL && !station_holds_media) {
        c300x_calls_media_closed(&hub->calls, &hub->sink, c300x_monotonic_ms());
    }
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
        } else {
            c300x_calls_hangup_started(&hub->calls, call_id);
        }
    }
    int done = answer ? c300x_http_doorbell_call_answer(client_fd, routes->control, routes->video, request)
                      : c300x_http_doorbell_call_hangup(client_fd, routes->control, routes->video);
    if (done) {
        if (answer) {
            c300x_calls_answered(&hub->calls, &hub->sink, call_id, "ha", c300x_monotonic_ms());
        } else {
            c300x_calls_end(&hub->calls, &hub->sink, call_id, "hangup", c300x_monotonic_ms());
        }
    } else if (routes->control == NULL || !c300x_video_control_deferred(routes->control)) {
        c300x_calls_action_refused(&hub->calls, call_id);
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

/* The unit, lock and call of an unlock; zero when it was answered with an error. */
static int resolve_unlock(int client_fd, struct c300x_call_hub *hub, const struct request *request,
                          const char *unit_id, struct c300x_unlock_resolved *resolved)
{
    int index = unit_index(hub, unit_id);

    memset(resolved, 0, sizeof(*resolved));
    if (index < 0) {
        c300x_http_send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"unknown_unit\"}\n");
        return 0;
    }
    if (c300x_json_string_field_checked(request->body, "call_id", resolved->call_id,
                                        sizeof(resolved->call_id)) < 0) {
        c300x_http_send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_call_id\"}\n");
        return 0;
    }
    if (resolved->call_id[0] != '\0'
        && !c300x_calls_unlock_allowed(&hub->calls, resolved->call_id, hub->units.items[index].id,
                                       c300x_monotonic_ms())) {
        send_not_current(client_fd, &hub->calls);
        return 0;
    }
    c300x_copy_string(resolved->unit, sizeof(resolved->unit), hub->units.items[index].id);
    c300x_copy_string(resolved->lock_where, sizeof(resolved->lock_where), hub->units.items[index].lock_where);
    return 1;
}

static void unlock(int client_fd, const struct c300x_call_routes *routes, const struct request *request,
                   const char *unit_id)
{
    struct c300x_call_hub *hub = routes->hub;
    struct c300x_unlock_resolved own;
    const struct c300x_unlock_resolved *resolved = &own;
    char press[48], release[48], error[C300X_MAX_ERROR_LEN], body[256];
    char error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];

    /* Its command may be out already: a later pass opens the unit the first
     * one chose, whatever call is current by then. */
    if (routes->openwebnet != NULL && c300x_openwebnet_async_owns(routes->openwebnet)) {
        resolved = &hub->unlock;
    } else if (!resolve_unlock(client_fd, hub, request, unit_id, &own)) {
        return;
    }
    snprintf(press, sizeof(press), "*8*19*%s##", resolved->lock_where);
    snprintf(release, sizeof(release), "*8*20*%s##", resolved->lock_where);
    if (!c300x_openwebnet_sequence(hub->config, press, hub->config->lock_release_delay_ms, release,
                                   error, sizeof(error))) {
        if (c300x_openwebnet_deferred()) {
            /* Kept only for the request whose command just started; one
             * that waits for the worker resolves again when its turn comes. */
            if (resolved == &own && routes->openwebnet != NULL && c300x_openwebnet_async_owns(routes->openwebnet)) {
                hub->unlock = own;
            }
            return;
        }
        snprintf(body, sizeof(body), "{\"ok\":false,\"error\":%s}\n",
                 c300x_json_string(error, error_json, sizeof(error_json)));
        c300x_http_send_json(client_fd, 502, "Bad Gateway", body);
        return;
    }
    const char *call_id = resolved->call_id;
    snprintf(body, sizeof(body), "{\"ok\":true,\"unit\":\"%s\",\"lock_where\":\"%s\",\"call_id\":%s%s%s}\n",
             resolved->unit, resolved->lock_where, call_id[0] ? "\"" : "null", call_id, call_id[0] ? "\"" : "");
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
    char segment[REQUEST_CALL_ID_LEN];
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
        if (segment[0] == '\0') {
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
