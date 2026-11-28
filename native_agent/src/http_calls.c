#include "http_calls.h"

#include <stdio.h>
#include <stdlib.h>
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
#include "video_rtsp.h"

#define CALLS_PREFIX "/api/v1/calls/"
/* Well-formed call ids in requests: 1-32 characters (the agent's own are shorter). */
#define REQUEST_CALL_ID_LEN ((int)sizeof(((struct c300x_unlock_resolved *)0)->call_id))
#define UNITS_PREFIX "/api/v1/outdoor-units/"

/* The units the agent saw, and those with a door contact, are written
 * where its configuration is. */
static void state_path(const struct c300x_config *config, const char *name, char *out, size_t out_len)
{
    const char *slash = config != NULL ? strrchr(config->config_path, '/') : NULL;

    out[0] = '\0';
    if (slash != NULL && (size_t)(slash - config->config_path) + strlen(name) + 2 <= out_len) {
        snprintf(out, out_len, "%.*s/%s", (int)(slash - config->config_path), config->config_path, name);
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
    state_path(config, "outdoor-units-seen", hub->seen_path, sizeof(hub->seen_path));
    state_path(config, "outdoor-units-doors", hub->doors_path, sizeof(hub->doors_path));
}

void c300x_call_hub_bind(struct c300x_call_hub *hub, struct c300x_video *const *video,
                         const struct c300x_video_control *control)
{
    hub->video = video;
    hub->control = control;
}

static void load_units(struct c300x_call_hub *hub)
{
    hub->sink.units = &hub->units;
    if (hub->config != NULL) {
        c300x_outdoor_units_load(&hub->units, C300X_ARCHIVE_XML_PATH, C300X_CONF_XML_PATH,
                                 hub->config->video_sip_devaddr, hub->config->lock_address);
    } else if (!hub->units.loaded) {
        static const struct c300x_station_archive nothing;
        c300x_outdoor_units_build(&hub->units, &nothing, "missing", "20", "20");
    }
    if (!hub->seen_loaded) {
        hub->seen_loaded = 1;
        c300x_outdoor_units_load_seen(&hub->units, hub->seen_path);
        c300x_door_contacts_load(&hub->doors, hub->doors_path);
    }
}

/* The agent's media state, as its ring session and display guard see it. */
static void media_state(const struct c300x_call_hub *hub, struct c300x_call_media *media)
{
    struct c300x_video_status status;

    memset(media, 0, sizeof(*media));
    if (hub->video != NULL && *hub->video != NULL) {
        c300x_video_status(*hub->video, &status);
        media->ring_leg = status.ring_call_active;
        media->ha_answered = status.ring_answered || status.ring_answer_requested;
        media->external = status.external_media_active;
        media->agent = status.call_active || status.bridge_media_active || status.media_starting;
    }
    media->ha_hangup = hub->stopping;
    if (hub->control != NULL && hub->control->worker.owner_fd != C300X_REQUEST_WORKER_FREE) {
        /* On the media worker: until its request is answered or gone. */
        media->ha_hangup |= hub->control->job.op == C300X_VIDEO_CONTROL_HANGUP
            || hub->control->job.op == C300X_VIDEO_CONTROL_STOP;
    }
}

/* *8*65/66*<where>##: the door of that unit closed or opened. */
static void door_frame(struct c300x_call_hub *hub, const char *frame, const char *where, int open)
{
    int changed = 0;
    int index = c300x_outdoor_units_note_caller(&hub->units, where, &changed);
    const struct c300x_outdoor_unit *unit = index >= 0 ? &hub->units.items[index] : NULL;
    int result = unit != NULL ? c300x_door_contacts_note(&hub->doors, unit->id, open, c300x_monotonic_ms()) : -1;
    char data[160];

    if (result == 2) {
        (void)c300x_door_contacts_save(&hub->doors, hub->doors_path);
    }
    if (changed || result == 2) {
        snprintf(data, sizeof(data), "{\"count\":%d}", hub->units.count);
        hub_emit(hub, "outdoor_units.changed", data);
    }
    if (result > 0) {
        /* frame and where are bus digits, '#' and '*' only. */
        snprintf(data, sizeof(data), "{\"unit\":\"%s\",\"where\":\"%s\",\"raw\":\"%s\"}", unit->id, where, frame);
        hub_emit(hub, open ? "door.opened" : "door.closed", data);
    }
}

void c300x_call_hub_frame(struct c300x_call_hub *hub, const char *frame)
{
    struct c300x_call_media media;
    char where[C300X_UNIT_WHERE_LEN];
    int code, open;

    if (hub != NULL && c300x_door_frame_parse(frame, &open, where, sizeof(where))) {
        if (!hub->units.loaded) load_units(hub);
        door_frame(hub, frame, where, open);
        return;
    }
    if (hub != NULL && c300x_station_state_parse(frame, &code)) {
        media_state(hub, &media);
        c300x_calls_station(&hub->calls, &hub->sink, &media, code, c300x_monotonic_ms());
        return;
    }
    if (hub == NULL || frame == NULL || strncmp(frame, "*8*", 3) != 0) {
        return;
    }
    if (!hub->units.loaded) {
        load_units(hub);
    }
    c300x_calls_frame(&hub->calls, &hub->sink, frame, c300x_monotonic_ms());
}

/* data with fields added before its closing brace; 1 when it does not fit. */
static int append_fields(const char *data, const char *fields, char *out, size_t out_len)
{
    size_t length = strlen(data);
    size_t used = 0;

    if (length < 2 || data[length - 1] != '}') {
        return 1;
    }
    out[0] = '\0';
    if (!c300x_appendf(out, out_len, &used, "%.*s%s%s}", (int)(length - 1), data, length > 2 ? "," : "", fields)) {
        return 1;
    }
    return 2;
}

/* data with ,"unit":...,"call_id":... added. */
static int decorate(const char *data, const char *unit, const char *call_id, char *out, size_t out_len)
{
    char fields[160];

    if (strstr(data, "\"unit\"") != NULL) {
        return 1;
    }
    snprintf(fields, sizeof(fields), "\"unit\":\"%s\",\"call_id\":%s%s%s", unit,
             call_id ? "\"" : "null", call_id ? call_id : "", call_id ? "\"" : "");
    return append_fields(data, fields, out, out_len);
}

/* The ring's own data with its call's id, unit and attribution. */
static int ring_fields(const struct c300x_call *call, const char *data, char *out, size_t out_len)
{
    char fields[160];
    char unit[C300X_JSON_QUOTED_LEN(C300X_UNIT_WHERE_LEN)];

    if (strstr(data, "\"call_id\"") != NULL) {
        return 1;
    }
    snprintf(fields, sizeof(fields), "\"call_id\":\"%s\",\"unit\":%s,\"attribution\":\"%s\"", call->id,
             c300x_json_string_or_null(call->unit[0] != '\0' ? call->unit : NULL, unit, sizeof(unit)),
             call->attribution);
    return append_fields(data, fields, out, out_len);
}

int c300x_call_hub_event(struct c300x_call_hub *hub, const char *type, const char *data,
                         char *out, size_t out_len)
{
    long long now = c300x_monotonic_ms();
    char text[C300X_UNIT_WHERE_LEN * 2];
    struct c300x_call_media media;

    if (hub == NULL || type == NULL || data == NULL) {
        return 1;
    }
    if (!hub->units.loaded) {
        load_units(hub);
    }
    if (strcmp(type, "doorbell.pressed") == 0) {
        return ring_fields(c300x_calls_ring(&hub->calls, &hub->sink, now), data, out, out_len);
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
        /* The ring answered: on the display or the app (*8*2#1#) or by the
         * agent's own answer (no frame). A view frame (*8*1#5#) opened its
         * view already. */
        c300x_json_string_field(data, "raw", text, sizeof(text));
        if (text[0] == '\0' || strncmp(text, "*8*2#1#", 7) == 0) {
            media_state(hub, &media);
            c300x_calls_answer_seen(&hub->calls, &hub->sink, &media, now);
        }
        const struct c300x_call *call = c300x_calls_current(&hub->calls);
        return call != NULL && call->unit[0] != '\0' ? decorate(data, call->unit, call->id, out, out_len) : 1;
    }
    return 1;
}

void c300x_call_hub_media_closed(struct c300x_call_hub *hub, int station_holds_media, int from_bus)
{
    struct c300x_call_media media;

    if (hub != NULL) {
        media_state(hub, &media);
        c300x_calls_media_closed(&hub->calls, &hub->sink, &media, station_holds_media, from_bus,
                                 c300x_monotonic_ms());
    }
}

int c300x_call_hub_timeout_ms(struct c300x_call_hub *hub)
{
    return c300x_calls_timeout_ms(&hub->calls, c300x_monotonic_ms());
}

static void tick(struct c300x_call_hub *hub)
{
    struct c300x_call_media media;

    media_state(hub, &media);
    c300x_calls_tick(&hub->calls, &hub->sink, &media, c300x_monotonic_ms());
}

void c300x_call_hub_tick(struct c300x_call_hub *hub)
{
    if (c300x_calls_timeout_ms(&hub->calls, c300x_monotonic_ms()) == 0) {
        tick(hub);
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

/* A view ends as HA's stop button ends it; 1 when the request was answered with success. */
static int stop_view(int client_fd, const struct c300x_call_routes *routes)
{
    const char *error = "";
    char body[96];
    int result = 0;

    if (routes->video == NULL) {
        c300x_http_send_json(client_fd, 503, "Service Unavailable", "{\"ok\":false,\"error\":\"video_unavailable\"}\n");
        return 0;
    }
    if (routes->control == NULL) {
        c300x_video_stop(routes->video);
    } else {
        enum c300x_video_control_state state = c300x_video_control_run(
            routes->control, routes->video, C300X_VIDEO_CONTROL_STOP, 0, NULL, &result, &error);
        if (state == C300X_VIDEO_CONTROL_DEFERRED) {
            return 0;
        }
        if (state == C300X_VIDEO_CONTROL_REFUSED) {
            snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}\n", error);
            c300x_http_send_json(client_fd, 503, "Service Unavailable", body);
            return 0;
        }
    }
    c300x_http_send_json(client_fd, 200, "OK", "{\"ok\":true}\n");
    return 1;
}

static void call_action(int client_fd, const struct c300x_call_routes *routes, const struct request *request,
                        const char *call_id, int answer)
{
    struct c300x_call_hub *hub = routes->hub;
    /* Checked before the operation starts, not when its result is answered. */
    int owns = routes->control != NULL && routes->control->worker.owner_fd == client_fd;
    const struct c300x_call *call = c300x_calls_find(&hub->calls, call_id);
    int done;

    if (!owns && !c300x_calls_is_current(&hub->calls, call_id)) {
        send_not_current(client_fd, &hub->calls);
        return;
    }
    if (call != NULL && call->view && answer) {
        c300x_http_send_json(client_fd, 409, "Conflict", "{\"ok\":false,\"error\":\"call_not_ringing\"}\n");
        return;
    }
    hub->stopping = !answer;
    if (call != NULL && call->view) {
        done = stop_view(client_fd, routes);
    } else {
        done = answer ? c300x_http_doorbell_call_answer(client_fd, routes->control, routes->video, request)
                      : c300x_http_doorbell_call_hangup(client_fd, routes->control, routes->video);
    }
    if (done && answer) {
        c300x_calls_answered(&hub->calls, &hub->sink, call_id, "ha", c300x_monotonic_ms());
    } else if (done) {
        c300x_calls_end(&hub->calls, &hub->sink, call_id, "hangup", c300x_monotonic_ms());
    }
    hub->stopping = 0;
}

/* unit_index: the current ring call has no unit yet. */
#define UNIT_PENDING (-2)

/* The ring call whose caller frame may still name its unit: until the
 * default unit stands in for it, "current" is none of the units. */
static const struct c300x_call *pending_call(const struct c300x_call_hub *hub, long long now)
{
    const struct c300x_call *call = c300x_calls_current(&hub->calls);

    return call != NULL && !call->view && call->unit[0] == '\0' && strcmp(call->attribution, "pending") == 0
        && now - call->started_ms < C300X_CALLER_WAIT_MS ? call : NULL;
}

/* "current": the current call's unit, else the default one; UNIT_PENDING
 * while the ring call's unit is not known. */
static int unit_index(struct c300x_call_hub *hub, const char *unit_id, long long now)
{
    if (strcmp(unit_id, "current") == 0) {
        const struct c300x_call *call = c300x_calls_current(&hub->calls);
        int index = call != NULL ? c300x_outdoor_units_find_id(&hub->units, call->unit) : -1;
        if (index < 0 && pending_call(hub, now) != NULL) {
            return UNIT_PENDING;
        }
        return index >= 0 ? index : hub->units.default_index;
    }
    return c300x_outdoor_units_find_id(&hub->units, unit_id);
}

/* Nothing is sent: the request can be repeated once the caller frame or
 * the default unit named the call's unit, at the latest after retry_after_ms. */
static void send_unit_pending(int client_fd, const struct c300x_call_hub *hub, long long now)
{
    const struct c300x_call *call = pending_call(hub, now);
    long long wait = call != NULL ? call->started_ms + C300X_CALLER_WAIT_MS - now : 0;
    char body[160];

    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"call_unit_pending\",\"call_id\":\"%s\",\"retry_after_ms\":%lld}\n",
             call != NULL ? call->id : "", wait > 0 ? wait : 1);
    c300x_http_send_json(client_fd, 409, "Conflict", body);
}

/* The unit, lock and call of an unlock; zero when it was answered with an error. */
static int resolve_unlock(int client_fd, struct c300x_call_hub *hub, const struct request *request,
                          const char *unit_id, struct c300x_unlock_resolved *resolved)
{
    long long now = c300x_monotonic_ms();
    int index = unit_index(hub, unit_id, now);

    memset(resolved, 0, sizeof(*resolved));
    if (index == UNIT_PENDING) {
        send_unit_pending(client_fd, hub, now);
        return 0;
    }
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
                                       now)) {
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

/* The station's call state is sent on changes only: once, while none was
 * seen since the agent started, the station is asked. Zero: the request
 * runs again with the answer. With the OpenWebNet queue full the list goes
 * out without the state, and a later request asks. */
static int ask_station_state(const struct c300x_call_routes *routes)
{
    struct c300x_call_hub *hub = routes->hub;
    int owns = routes->openwebnet != NULL && c300x_openwebnet_async_owns(routes->openwebnet);
    char reply[64], error[C300X_MAX_ERROR_LEN];
    struct c300x_call_media media;
    int code;

    /* Once its query is out, only its answer ends the request. */
    if (!owns && (hub->station_asked || hub->config == NULL
                  || hub->calls.station_state != C300X_STATION_STATE_UNKNOWN)) {
        return 1;
    }
    if (!c300x_openwebnet_send(hub->config, "*#8**35##", reply, sizeof(reply), error, sizeof(error))) {
        if (c300x_openwebnet_deferred()) {
            return routes->openwebnet != NULL && c300x_openwebnet_async_drop_refusal(routes->openwebnet);
        }
    } else if (c300x_station_state_parse(reply, &code) && hub->calls.station_state == C300X_STATION_STATE_UNKNOWN) {
        media_state(hub, &media);
        c300x_calls_station(&hub->calls, &hub->sink, &media, code, c300x_monotonic_ms());
    }
    hub->station_asked = 1;
    return 1;
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

/* The ring's own media answers a video request, whatever unit it names. */
static int ring_media_answers(const struct c300x_call_routes *routes)
{
    struct c300x_video_status status;

    c300x_video_status(routes->video, &status);
    return status.ring_call_active || status.ring_media_active;
}

static void video_activate(int client_fd, const struct c300x_call_routes *routes, const struct request *request)
{
    char unit_id[C300X_UNIT_WHERE_LEN] = "";
    struct c300x_call_hub *hub = routes->hub;
    long long now = c300x_monotonic_ms();
    const struct c300x_video_control *control = routes->control;

    /* Its activation is out already: a later pass takes the unit the first
     * one chose, whatever call is current by then. */
    if (control != NULL && control->worker.owner_fd == client_fd && control->job.op == C300X_VIDEO_CONTROL_ACTIVATE) {
        c300x_http_doorbell_video_activate(client_fd, routes->control, routes->video, request,
                                           control->job.where[0] != '\0' ? control->job.where : NULL);
        return;
    }
    int checked = c300x_json_string_field_checked(request->body, "unit", unit_id, sizeof(unit_id));
    /* Without a unit: the current call's, else the default. */
    int index = unit_index(hub, checked > 0 ? unit_id : "current", now);
    /* Without video the request is answered video_unavailable. */
    int ring = routes->video == NULL || ring_media_answers(routes);

    if (checked >= 0 && index == UNIT_PENDING) {
        if (!ring) {
            send_unit_pending(client_fd, hub, now);
            return;
        }
        index = hub->units.default_index;
    }
    if (checked < 0 || index < 0) {
        c300x_http_send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"unknown_unit\"}\n");
        return;
    }
    /* The ring's media shows its caller whatever unit is asked; a view does
     * not. On demand the default unit is the configured DEVADDR, as before;
     * another unit's DEVADDR is its full address, which the station takes
     * verbatim. */
    const char *where = hub->units.items[index].where;
    if (index != hub->units.default_index && !ring && !c300x_media_devaddr_valid(where)) {
        c300x_http_send_json(client_fd, 409, "Conflict", "{\"ok\":false,\"error\":\"unit_video_unsupported\"}\n");
        return;
    }
    c300x_http_doorbell_video_activate(client_fd, routes->control, routes->video, request,
                                       index != hub->units.default_index ? where : NULL);
}

int c300x_http_calls_route(int client_fd, const struct c300x_call_routes *routes, const struct request *request)
{
    struct c300x_call_hub *hub = routes->hub;
    char segment[REQUEST_CALL_ID_LEN];
    char body[4096];
    int get = strcmp(request->method, "GET") == 0;
    int post = strcmp(request->method, "POST") == 0;

    if (strcmp(request->path, "/api/v1/outdoor-units") == 0 && get) {
        char *units = malloc(C300X_OUTDOOR_UNITS_JSON_SIZE);
        load_units(hub);
        /* Sized for the worst case: a unit list that does not fit is a bug. */
        if (units == NULL || !c300x_outdoor_units_json(&hub->units, &hub->doors, c300x_monotonic_ms(), units,
                                                       C300X_OUTDOOR_UNITS_JSON_SIZE)) {
            c300x_http_send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        } else {
            c300x_http_send_json(client_fd, 200, "OK", units);
        }
        free(units);
        return 1;
    }
    if (strcmp(request->path, "/api/v1/calls") == 0 && get) {
        if (!hub->units.loaded) load_units(hub);
        if (!ask_station_state(routes)) return 1;
        tick(hub);
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
