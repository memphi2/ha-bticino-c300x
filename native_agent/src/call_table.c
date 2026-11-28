#include "call_table.h"

#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "json_util.h"
#include "string_util.h"

#define FRAME_LEN 64

static int live(const struct c300x_call *call)
{
    return call->state == C300X_CALL_RINGING || call->state == C300X_CALL_ANSWERED
        || call->state == C300X_CALL_VIEWING;
}

static void draw_boot_id(struct c300x_calls *calls)
{
    unsigned char bytes[4] = {0};
    int fd;

    fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (fd < 0 || read(fd, bytes, sizeof(bytes)) != (ssize_t)sizeof(bytes)) {
        unsigned long fallback = (unsigned long)time(NULL) ^ (unsigned long)getpid();
        memcpy(bytes, &fallback, sizeof(bytes));
    }
    if (fd >= 0) {
        close(fd);
    }
    snprintf(calls->boot_id, sizeof(calls->boot_id), "%02x%02x%02x%02x", bytes[0], bytes[1], bytes[2], bytes[3]);
}

void c300x_calls_init(struct c300x_calls *calls, const char *boot_id)
{
    memset(calls, 0, sizeof(*calls));
    calls->station_state = C300X_STATION_STATE_UNKNOWN;
    calls->idle_ms = -1;
    if (boot_id != NULL && boot_id[0] != '\0') {
        c300x_copy_string(calls->boot_id, sizeof(calls->boot_id), boot_id);
    } else {
        draw_boot_id(calls);
    }
}

static void emit(const struct c300x_call_sink *sink, const char *type, const char *data)
{
    if (sink != NULL && sink->emit != NULL) {
        sink->emit(sink->context, type, data);
    }
}

static const char *unit_json(const struct c300x_call *call, char *out, size_t out_len)
{
    return c300x_json_string_or_null(call->unit[0] != '\0' ? call->unit : NULL, out, out_len);
}

static int ring_live(const struct c300x_call *call)
{
    return !call->view && (call->state == C300X_CALL_RINGING || call->state == C300X_CALL_ANSWERED);
}

/* A free slot, else the oldest ended call, else the oldest view. */
static struct c300x_call *slot(struct c300x_calls *calls, const struct c300x_call_sink *sink, long long now)
{
    struct c300x_call *oldest = NULL;

    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        struct c300x_call *call = &calls->items[index];
        if (call->state == C300X_CALL_FREE) {
            return call;
        }
        int ended = call->state == C300X_CALL_ENDED;
        int oldest_ended = oldest != NULL && oldest->state == C300X_CALL_ENDED;
        if (!ring_live(call) && (oldest == NULL || (ended && !oldest_ended)
            || (ended == oldest_ended && call->updated_ms < oldest->updated_ms))) {
            oldest = call;
        }
    }
    if (oldest == NULL) {
        oldest = &calls->items[0];
    }
    c300x_calls_end(calls, sink, oldest->id, "superseded", now);
    return oldest;
}

static struct c300x_call *open_call(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                                    int view, long long now)
{
    struct c300x_call *call = slot(calls, sink, now);

    memset(call, 0, sizeof(*call));
    snprintf(call->id, sizeof(call->id), "%s-%lu", calls->boot_id, ++calls->seq);
    call->state = view ? C300X_CALL_VIEWING : C300X_CALL_RINGING;
    call->view = view;
    call->attribution = "pending";
    call->started_ms = call->updated_ms = now;
    call->probe_ms = view ? now + C300X_CALL_PROBE_MS : 0;
    return call;
}

/* The ring session's call: at most one is live. */
static struct c300x_call *ring_call(struct c300x_calls *calls)
{
    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        if (ring_live(&calls->items[index])) {
            return &calls->items[index];
        }
    }
    return NULL;
}

static struct c300x_call *live_view(struct c300x_calls *calls, const char *unit)
{
    struct c300x_call *found = NULL;

    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        struct c300x_call *call = &calls->items[index];
        if (call->view && live(call) && (unit == NULL || strcmp(call->unit, unit) == 0)
            && (found == NULL || call->started_ms > found->started_ms)) {
            found = call;
        }
    }
    return found;
}

const struct c300x_call *c300x_calls_ring(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                                          long long now)
{
    struct c300x_call *call = ring_call(calls);

    if (call != NULL && call->closing != NULL) {
        /* Its ring ended unanswered: this press rings anew. */
        c300x_calls_end(calls, sink, call->id, call->closing, now);
        call = NULL;
    }
    if (call == NULL) {
        return open_call(calls, sink, 0, now);
    }
    if (call->state == C300X_CALL_RINGING) {
        call->updated_ms = now;
    }
    return call;
}

static void name_unit(struct c300x_call *call, const struct c300x_call_sink *sink,
                      const struct c300x_outdoor_unit *unit, const char *attribution, const char *raw)
{
    char data[512];
    char raw_json[C300X_JSON_QUOTED_LEN(FRAME_LEN)];
    size_t used = 0;

    if (strcmp(call->unit, unit->id) == 0 && strcmp(call->attribution, attribution) == 0) {
        return;
    }
    c300x_copy_string(call->unit, sizeof(call->unit), unit->id);
    call->attribution = attribution;
    if (c300x_appendf(data, sizeof(data), &used,
            "{\"call_id\":\"%s\",\"unit\":\"%s\",\"where\":\"%s\",\"action_where\":\"%s\","
            "\"attribution\":\"%s\",\"raw\":%s}",
            call->id, unit->id, unit->where, unit->action_where, attribution,
            c300x_json_string_or_null(raw, raw_json, sizeof(raw_json)))) {
        emit(sink, "call.caller_identified", data);
    }
}

static void units_changed(const struct c300x_call_sink *sink)
{
    char data[48];
    snprintf(data, sizeof(data), "{\"count\":%d}", sink->units->count);
    emit(sink, "outdoor_units.changed", data);
}

static const struct c300x_outdoor_unit *resolve(const struct c300x_call_sink *sink, const char *where)
{
    int changed = 0;
    int index;

    if (sink == NULL || sink->units == NULL) {
        return NULL;
    }
    index = c300x_outdoor_units_note_caller(sink->units, where, &changed);
    if (changed) {
        units_changed(sink);
    }
    return index >= 0 ? &sink->units->items[index] : NULL;
}

/* The caller frame names the unit of the ring session's call, ringing or
 * answered, also after the default unit stood in for it. */
static void caller(struct c300x_calls *calls, const struct c300x_call_sink *sink, const char *where,
                   const char *raw)
{
    struct c300x_call *call = ring_call(calls);
    const struct c300x_outdoor_unit *unit = call != NULL ? resolve(sink, where) : NULL;

    if (unit == NULL) {
        calls->caller_frames_ignored++;
        return;
    }
    name_unit(call, sink, unit, "caller_frame", raw);
}

static void view_started(struct c300x_calls *calls, const struct c300x_call_sink *sink, const char *where,
                         long long now)
{
    const struct c300x_outdoor_unit *unit = resolve(sink, where);
    struct c300x_call *call;
    char data[160];

    if (unit == NULL) {
        return;
    }
    call = live_view(calls, unit->id);
    if (call != NULL) {
        call->updated_ms = now;
        return;
    }
    /* The station shows one view at a time. */
    while ((call = live_view(calls, NULL)) != NULL) {
        c300x_calls_end(calls, sink, call->id, "superseded", now);
    }
    call = open_call(calls, sink, 1, now);
    c300x_copy_string(call->unit, sizeof(call->unit), unit->id);
    call->attribution = "caller_frame";
    snprintf(data, sizeof(data), "{\"call_id\":\"%s\",\"unit\":\"%s\"}", call->id, unit->id);
    emit(sink, "call.view_started", data);
}

/* *8*<what>#<kind>#<mode>[#<where>]*<where>## */
void c300x_calls_frame(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                       const char *frame, long long now)
{
    int what, kind, mode, consumed = 0;
    char head_where[C300X_UNIT_WHERE_LEN] = "";
    char tail_where[C300X_UNIT_WHERE_LEN] = "";
    const char *star;
    size_t length;

    if (frame == NULL || strlen(frame) >= FRAME_LEN
        || sscanf(frame, "*8*%d#%d#%d%n", &what, &kind, &mode, &consumed) != 3 || consumed == 0) {
        return;
    }
    star = strchr(frame + consumed, '*');
    length = strlen(frame);
    if (star == NULL || length < 2 || strcmp(frame + length - 2, "##") != 0) {
        return;
    }
    if (frame[consumed] == '#' && (size_t)(star - frame - consumed - 1) < sizeof(head_where)) {
        memcpy(head_where, frame + consumed + 1, (size_t)(star - frame - consumed - 1));
        head_where[star - frame - consumed - 1] = '\0';
    } else if (star != frame + consumed) {
        return;
    }
    if ((size_t)(frame + length - 2 - star - 1) < sizeof(tail_where)) {
        memcpy(tail_where, star + 1, (size_t)(frame + length - 2 - star - 1));
        tail_where[frame + length - 2 - star - 1] = '\0';
    }
    /* Only the caller and the view frame name a unit. Start, answer and end
     * come from the agent's ring and media events. */
    if (what == 9 && kind == 1 && head_where[0] == '\0') {
        caller(calls, sink, tail_where, frame);
    } else if (what == 1 && kind == 5 && head_where[0] != '\0') {
        view_started(calls, sink, head_where, now);
    }
}

void c300x_calls_station(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                         const struct c300x_call_media *media, int code, long long now)
{
    struct c300x_call *call = ring_call(calls);
    const char *name = c300x_station_state_name(code);
    char data[96];

    if (code == calls->station_state) {
        return;
    }
    calls->station_state = code;
    calls->station_ms = now;
    calls->idle_ms = code == 0 ? now : -1;
    snprintf(data, sizeof(data), "{\"code\":%d,\"state\":%s%s%s}", code, name ? "\"" : "", name ? name : "null",
             name ? "\"" : "");
    emit(sink, "station.call_state", data);
    /* Every on-demand view reports 3, then 6: during the agent's own view
     * without its ring leg, 6 is that view's; the display's answer frame
     * still answers the ring. */
    if (code == 6 && media->agent && !media->ring_leg) {
        return;
    }
    if (call != NULL && call->state == C300X_CALL_RINGING && (code == 6 || code == 7)) {
        c300x_calls_answered(calls, sink, call->id,
                             code == 7 ? "answering_machine" : media->ha_answered ? "ha" : "station", now);
    }
}

void c300x_calls_answer_seen(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                             const struct c300x_call_media *media, long long now)
{
    struct c300x_call *call = ring_call(calls);

    if (call != NULL) {
        c300x_calls_answered(calls, sink, call->id, media->ha_answered ? "ha" : "station", now);
    }
}

void c300x_calls_media_closed(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                              const struct c300x_call_media *media, int view, int external, int from_bus,
                              long long now)
{
    const char *reason = media->ha_hangup ? "hangup" : "media_closed";

    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        struct c300x_call *call = &calls->items[index];
        /* A view's close ends no ring, the ring's no view. */
        if (!live(call) || call->view != view) {
            continue;
        }
        if (external) {
            /* The station's media goes on: the display or the app has the call. */
            if (call->state == C300X_CALL_RINGING) {
                c300x_calls_answered(calls, sink, call->id, "station", now);
            }
            continue;
        }
        if (call->state == C300X_CALL_RINGING && !media->ha_hangup) {
            /* Unanswered, or answered on the display or the app with the
             * answer frame still to come. */
            if (call->closing == NULL) {
                call->closing = reason;
                call->closed_ms = now;
            }
        } else if (call->state != C300X_CALL_ANSWERED || from_bus || strcmp(call->answered_by, "ha") == 0) {
            /* A station call ends with the bus end frame, not with the agent's leg. */
            c300x_calls_end(calls, sink, call->id, reason, now);
        }
    }
}

/* The media the call stands for is still there; a call the station holds
 * lives while the station's state is not idle. */
static int media_live(const struct c300x_calls *calls, const struct c300x_call *call,
                      const struct c300x_call_media *media)
{
    if (call->view) {
        return media->agent || media->external;
    }
    return media->ring_leg
        || (strcmp(call->answered_by, "ha") != 0 && (media->external || calls->station_state > 0));
}

/* The station went idle while the call was live. */
static int station_idle(const struct c300x_calls *calls, const struct c300x_call *call)
{
    return calls->idle_ms >= 0 && live(call) && call->started_ms <= calls->idle_ms;
}

/* A ring call, ringing or answered before its caller wait was over, that
 * no caller frame named yet. */
static int caller_pending(const struct c300x_call *call)
{
    return ring_live(call) && strcmp(call->attribution, "pending") == 0;
}

static long long call_deadline(const struct c300x_call *call)
{
    long long due;

    if (call->state == C300X_CALL_RINGING) {
        due = call->updated_ms + C300X_CALL_RINGING_TIMEOUT_MS;
        if (call->closing != NULL && call->closed_ms + C300X_CALL_SETTLE_MS < due) {
            due = call->closed_ms + C300X_CALL_SETTLE_MS;
        }
    } else if (call->state == C300X_CALL_ENDED) {
        return call->updated_ms + C300X_CALL_ENDED_KEEP_MS;
    } else if (live(call)) {
        due = call->probe_ms;
    } else {
        return -1;
    }
    if (caller_pending(call) && call->started_ms + C300X_CALLER_WAIT_MS < due) {
        due = call->started_ms + C300X_CALLER_WAIT_MS;
    }
    return due;
}

static long long deadline(const struct c300x_calls *calls, const struct c300x_call *call)
{
    long long due = call_deadline(call);

    if (station_idle(calls, call) && (due < 0 || calls->idle_ms + C300X_CALL_SETTLE_MS < due)) {
        due = calls->idle_ms + C300X_CALL_SETTLE_MS;
    }
    return due;
}

static void fall_back(struct c300x_call *call, const struct c300x_call_sink *sink)
{
    const struct c300x_outdoor_unit *unit = sink != NULL && sink->units != NULL
        ? c300x_outdoor_units_default(sink->units) : NULL;

    if (unit != NULL) {
        name_unit(call, sink, unit, "default_fallback", NULL);
    } else {
        call->attribution = "default_fallback";
    }
}

void c300x_calls_tick(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                      const struct c300x_call_media *media, long long now)
{
    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        struct c300x_call *call = &calls->items[index];
        long long due = deadline(calls, call);
        if (due < 0 || now < due) {
            continue;
        }
        if (station_idle(calls, call) && now - calls->idle_ms >= C300X_CALL_SETTLE_MS) {
            c300x_calls_end(calls, sink, call->id, call->closing != NULL ? call->closing : "station_idle", now);
            continue;
        }
        if (call->state == C300X_CALL_ENDED) {
            memset(call, 0, sizeof(*call));
            continue;
        }
        if (caller_pending(call) && now - call->started_ms >= C300X_CALLER_WAIT_MS) {
            fall_back(call, sink);
        }
        if (call->state == C300X_CALL_RINGING) {
            if (call->closing != NULL && now - call->closed_ms >= C300X_CALL_SETTLE_MS) {
                c300x_calls_end(calls, sink, call->id, call->closing, now);
            } else if (now - call->updated_ms >= C300X_CALL_RINGING_TIMEOUT_MS) {
                c300x_calls_end(calls, sink, call->id, "timeout", now);
            }
        } else if (now < call->probe_ms) {
            /* Only the caller wait was due. */
        } else if (!media_live(calls, call, media)) {
            c300x_calls_end(calls, sink, call->id, "media_closed", now);
        } else {
            call->probe_ms = now + C300X_CALL_PROBE_MS;
        }
    }
}

int c300x_calls_timeout_ms(const struct c300x_calls *calls, long long now)
{
    long long next = -1;

    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        long long due = deadline(calls, &calls->items[index]);
        if (due >= 0 && (next < 0 || due < next)) {
            next = due;
        }
    }
    if (next < 0) {
        return -1;
    }
    return next <= now ? 0 : (int)(next - now);
}

const struct c300x_call *c300x_calls_find(const struct c300x_calls *calls, const char *call_id)
{
    for (int index = 0; call_id != NULL && call_id[0] != '\0' && index < C300X_MAX_CALLS; index++) {
        if (calls->items[index].state != C300X_CALL_FREE && strcmp(calls->items[index].id, call_id) == 0) {
            return &calls->items[index];
        }
    }
    return NULL;
}

const struct c300x_call *c300x_calls_current(const struct c300x_calls *calls)
{
    struct c300x_calls *mutable_calls = (struct c300x_calls *)calls;
    const struct c300x_call *call = ring_call(mutable_calls);
    return call != NULL ? call : live_view(mutable_calls, NULL);
}

const struct c300x_call *c300x_calls_media_call(const struct c300x_calls *calls, int view)
{
    struct c300x_calls *mutable_calls = (struct c300x_calls *)calls;
    return view ? live_view(mutable_calls, NULL) : ring_call(mutable_calls);
}

const struct c300x_call *c300x_calls_live_for_unit(const struct c300x_calls *calls, const char *unit)
{
    struct c300x_calls *mutable_calls = (struct c300x_calls *)calls;
    const struct c300x_call *call = ring_call(mutable_calls);
    return call != NULL && strcmp(call->unit, unit) == 0 ? call : live_view(mutable_calls, unit);
}

int c300x_calls_is_current(const struct c300x_calls *calls, const char *call_id)
{
    const struct c300x_call *current = c300x_calls_current(calls);
    return current != NULL && call_id != NULL && strcmp(current->id, call_id) == 0;
}

int c300x_calls_unlock_allowed(const struct c300x_calls *calls, const char *call_id,
                               const char *unit, long long now)
{
    const struct c300x_call *call = c300x_calls_find(calls, call_id);
    return call != NULL && strcmp(call->unit, unit) == 0
        && (live(call) || now - call->updated_ms < C300X_CALL_ENDED_KEEP_MS);
}

const char *c300x_calls_hangup_refusal(const struct c300x_call *call, const struct c300x_call_media *media)
{
    if (!live(call)) {
        return "call_not_current";
    }
    if (call->view) {
        return media->external && !media->agent ? "station_busy" : NULL;
    }
    if (call->state == C300X_CALL_ANSWERED) {
        return strcmp(call->answered_by, "ha") == 0 ? NULL : "station_busy";
    }
    return media->ring_leg ? NULL : "ring_call_not_active";
}

void c300x_calls_answered(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                          const char *call_id, const char *by, long long now)
{
    struct c300x_call *call = (struct c300x_call *)c300x_calls_find(calls, call_id);
    char unit[C300X_JSON_QUOTED_LEN(C300X_UNIT_WHERE_LEN)];
    char data[192];

    if (call == NULL || call->state != C300X_CALL_RINGING) {
        return;
    }
    call->state = C300X_CALL_ANSWERED;
    call->answered_by = by;
    call->closing = NULL;
    call->closed_ms = 0;
    call->probe_ms = now + C300X_CALL_GUARD_MS;
    call->updated_ms = now;
    snprintf(data, sizeof(data), "{\"call_id\":\"%s\",\"unit\":%s,\"answered_by\":\"%s\"}",
             call->id, unit_json(call, unit, sizeof(unit)), by);
    emit(sink, "call.answered", data);
}

void c300x_calls_end(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                     const char *call_id, const char *reason, long long now)
{
    struct c300x_call *call = (struct c300x_call *)c300x_calls_find(calls, call_id);
    char unit[C300X_JSON_QUOTED_LEN(C300X_UNIT_WHERE_LEN)];
    char data[224];

    if (call == NULL || !live(call)) {
        return;
    }
    call->state = C300X_CALL_ENDED;
    call->end_reason = reason;
    call->closing = NULL;
    call->updated_ms = now;
    snprintf(data, sizeof(data), "{\"call_id\":\"%s\",\"unit\":%s,\"kind\":\"%s\",\"reason\":\"%s\"}",
             call->id, unit_json(call, unit, sizeof(unit)), call->view ? "view" : "ring", reason);
    emit(sink, "call.ended", data);
}

static const char *state_name(enum c300x_call_state state)
{
    static const char *const names[] = {"free", "ringing", "answered", "viewing", "ended"};
    return names[state];
}

int c300x_calls_json(const struct c300x_calls *calls, const struct c300x_call_media *media, long long now,
                     char *out, size_t out_len)
{
    const struct c300x_call *current = c300x_calls_current(calls);
    const struct c300x_call *listed[C300X_MAX_CALLS];
    int count = 0;
    size_t used = 0;
    char unit[C300X_JSON_QUOTED_LEN(C300X_UNIT_WHERE_LEN)];

    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        const struct c300x_call *call = &calls->items[index];
        if (call->state == C300X_CALL_FREE
            || (call->state == C300X_CALL_ENDED && now - call->updated_ms >= C300X_CALL_ENDED_KEEP_MS)) {
            continue;
        }
        int at = count++;
        while (at > 0 && listed[at - 1]->started_ms < call->started_ms) {
            listed[at] = listed[at - 1];
            at--;
        }
        listed[at] = call;
    }
    if (!c300x_appendf(out, out_len, &used, "{\"ok\":true,\"boot_id\":\"%s\",\"current_call_id\":%s%s%s,"
                       "\"caller_frames_ignored\":%lu,\"station_state\":", calls->boot_id,
                       current ? "\"" : "null", current ? current->id : "", current ? "\"" : "",
                       calls->caller_frames_ignored)) {
        return 0;
    }
    if (calls->station_state == C300X_STATION_STATE_UNKNOWN) {
        if (!c300x_appendf(out, out_len, &used, "null")) return 0;
    } else {
        const char *name = c300x_station_state_name(calls->station_state);
        if (!c300x_appendf(out, out_len, &used, "{\"code\":%d,\"state\":%s%s%s,\"age_ms\":%lld}",
                           calls->station_state, name ? "\"" : "", name ? name : "null", name ? "\"" : "",
                           now - calls->station_ms)) {
            return 0;
        }
    }
    if (!c300x_appendf(out, out_len, &used, ",\"calls\":[")) {
        return 0;
    }
    for (int index = 0; index < count; index++) {
        const struct c300x_call *call = listed[index];
        if (!c300x_appendf(out, out_len, &used,
                "%s{\"call_id\":\"%s\",\"kind\":\"%s\",\"state\":\"%s\",\"unit\":%s,\"attribution\":\"%s\","
                "\"answered_by\":%s%s%s,\"end_reason\":%s%s%s,\"age_ms\":%lld,\"can_hangup\":%s}",
                index > 0 ? "," : "", call->id, call->view ? "view" : "ring", state_name(call->state),
                unit_json(call, unit, sizeof(unit)), call->attribution,
                call->answered_by ? "\"" : "null", call->answered_by ? call->answered_by : "",
                call->answered_by ? "\"" : "",
                call->end_reason ? "\"" : "null", call->end_reason ? call->end_reason : "",
                call->end_reason ? "\"" : "", now - call->started_ms,
                c300x_calls_hangup_refusal(call, media) == NULL ? "true" : "false")) {
            return 0;
        }
    }
    return c300x_appendf(out, out_len, &used, "]}\n");
}
