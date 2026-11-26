#include "call_table.h"

#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "json_util.h"
#include "string_util.h"

#define SIP_RING_MERGE_MS 5000
#define FRAME_LEN 64

static int live(const struct c300x_call *call)
{
    return call->state == C300X_CALL_RINGING || call->state == C300X_CALL_ANSWERED
        || call->state == C300X_CALL_VIEWING;
}

void c300x_calls_init(struct c300x_calls *calls, const char *boot_id)
{
    memset(calls, 0, sizeof(*calls));
    c300x_copy_string(calls->boot_id, sizeof(calls->boot_id), boot_id);
}

static void ensure_boot_id(struct c300x_calls *calls)
{
    unsigned char bytes[4] = {0};
    int fd;

    if (calls->boot_id[0] != '\0') {
        return;
    }
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

/* A free slot, else the oldest ended call, else the oldest live one. */
static struct c300x_call *slot(struct c300x_calls *calls)
{
    struct c300x_call *oldest = NULL;

    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        struct c300x_call *call = &calls->items[index];
        if (call->state == C300X_CALL_FREE) {
            return call;
        }
        int ended = call->state == C300X_CALL_ENDED;
        int oldest_ended = oldest != NULL && oldest->state == C300X_CALL_ENDED;
        if (oldest == NULL || (ended && !oldest_ended)
            || (ended == oldest_ended && call->updated_ms < oldest->updated_ms)) {
            oldest = call;
        }
    }
    return oldest;
}

static struct c300x_call *open_call(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                                    int view, long long now)
{
    struct c300x_call *call;

    ensure_boot_id(calls);
    call = slot(calls);
    if (live(call)) {
        c300x_calls_end(calls, sink, call->id, "evicted", now);
    }
    memset(call, 0, sizeof(*call));
    snprintf(call->id, sizeof(call->id), "%s-%lu", calls->boot_id, ++calls->seq);
    call->state = view ? C300X_CALL_VIEWING : C300X_CALL_RINGING;
    call->view = view;
    call->attribution = "pending";
    call->started_ms = call->last_ring_ms = call->updated_ms = now;
    return call;
}

static struct c300x_call *newest(struct c300x_calls *calls, enum c300x_call_state state, int need_unbound)
{
    struct c300x_call *found = NULL;

    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        struct c300x_call *call = &calls->items[index];
        if (call->state == state && !call->view && (!need_unbound || call->unit[0] == '\0')
            && (found == NULL || call->started_ms > found->started_ms)) {
            found = call;
        }
    }
    return found;
}

static struct c300x_call *live_for_unit(struct c300x_calls *calls, const char *unit, int view)
{
    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        struct c300x_call *call = &calls->items[index];
        if (live(call) && call->view == view && strcmp(call->unit, unit) == 0) {
            return call;
        }
    }
    return NULL;
}

static int ring_data(const struct c300x_call *call, const char *raw, char *data, size_t data_len)
{
    char raw_json[C300X_JSON_QUOTED_LEN(FRAME_LEN)];
    char unit[C300X_JSON_QUOTED_LEN(C300X_UNIT_WHERE_LEN)];
    size_t used = 0;

    data[0] = '\0';
    return c300x_appendf(data, data_len, &used,
        "{\"raw\":%s,\"call_id\":\"%s\",\"unit\":%s,\"attribution\":\"%s\"}",
        c300x_json_string_or_null(raw, raw_json, sizeof(raw_json)), call->id,
        unit_json(call, unit, sizeof(unit)), call->attribution);
}

int c300x_calls_ring(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                     const char *raw, long long now, char *data, size_t data_len)
{
    int from_sip = raw == NULL || raw[0] == '\0';
    struct c300x_call *call = newest(calls, C300X_CALL_RINGING, 0);

    if (call != NULL && (now - call->last_ring_ms < C300X_RING_REPEAT_MS
                         || (from_sip && now - call->started_ms < SIP_RING_MERGE_MS))) {
        if (!from_sip) {
            call->last_ring_ms = now;
        }
        if (call->unit[0] != '\0') {
            calls->repeat_after_bind_ms = now;
        }
        return 0;
    }
    call = open_call(calls, sink, 0, now);
    return ring_data(call, from_sip ? NULL : raw, data, data_len);
}

static void bind_unit(struct c300x_calls *calls, const struct c300x_call_sink *sink, struct c300x_call *call,
                      const struct c300x_outdoor_unit *unit, const char *attribution, const char *raw,
                      long long now)
{
    char data[512];
    char raw_json[C300X_JSON_QUOTED_LEN(FRAME_LEN)];
    struct c300x_call *older = live_for_unit(calls, unit->id, 0);
    size_t used = 0;

    if (older != NULL && older != call && older->state == C300X_CALL_RINGING) {
        c300x_calls_end(calls, sink, older->id, "superseded", now);
    }
    c300x_copy_string(call->unit, sizeof(call->unit), unit->id);
    call->attribution = attribution;
    call->bound_ms = call->updated_ms = now;
    calls->repeat_after_bind_ms = 0;
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

static void caller(struct c300x_calls *calls, const struct c300x_call_sink *sink, const char *where,
                   const char *raw, long long now)
{
    const struct c300x_outdoor_unit *unit = resolve(sink, where);
    struct c300x_call *call;
    char data[512];

    if (unit == NULL) {
        calls->caller_frames_ignored++;
        return;
    }
    call = newest(calls, C300X_CALL_RINGING, 1);
    if (call != NULL && now - call->started_ms <= C300X_CALLER_BIND_WINDOW_MS) {
        bind_unit(calls, sink, call, unit, "caller_frame", raw, now);
        return;
    }
    if (live_for_unit(calls, unit->id, 0) != NULL) {
        return;
    }
    if (calls->repeat_after_bind_ms > 0 && now - calls->repeat_after_bind_ms <= C300X_RING_REPEAT_MS) {
        /* A ring copy came after the newest call had its unit: another unit rings. */
        call = open_call(calls, sink, 0, now);
        c300x_copy_string(call->unit, sizeof(call->unit), unit->id);
        call->attribution = "caller_frame";
        if (ring_data(call, NULL, data, sizeof(data))) {
            emit(sink, "doorbell.pressed", data);
        }
        call->unit[0] = '\0';
        bind_unit(calls, sink, call, unit, "caller_frame", raw, now);
        return;
    }
    calls->caller_frames_ignored++;
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
    call = live_for_unit(calls, unit->id, 1);
    if (call != NULL) {
        call->updated_ms = now;
        return;
    }
    call = open_call(calls, sink, 1, now);
    c300x_copy_string(call->unit, sizeof(call->unit), unit->id);
    call->attribution = "caller_frame";
    call->bound_ms = now;
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
     * come from the agent's ring and media events: *8*100 follows an answer
     * or a view start by 100-500 ms and is no end. */
    if (what == 9 && kind == 1 && head_where[0] == '\0') {
        caller(calls, sink, tail_where, frame, now);
    } else if (what == 1 && kind == 5 && head_where[0] != '\0') {
        view_started(calls, sink, head_where, now);
    }
}

void c300x_calls_answer_seen(struct c300x_calls *calls, const struct c300x_call_sink *sink, long long now)
{
    struct c300x_call *call = newest(calls, C300X_CALL_RINGING, 0);

    if (call != NULL) {
        c300x_calls_answered(calls, sink, call->id, call->answer_pending ? "ha" : "station", now);
    }
}

void c300x_calls_media_closed(struct c300x_calls *calls, const struct c300x_call_sink *sink, long long now)
{
    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        if (live(&calls->items[index])) {
            c300x_calls_end(calls, sink, calls->items[index].id,
                            calls->items[index].hangup_pending ? "hangup" : "media_closed", now);
        }
    }
}

static long long deadline(const struct c300x_call *call)
{
    if (call->state == C300X_CALL_RINGING) {
        long long timeout = call->updated_ms + C300X_CALL_RINGING_TIMEOUT_MS;
        if (call->unit[0] == '\0' && call->bound_ms == 0 && call->started_ms + C300X_CALLER_WAIT_MS < timeout) {
            return call->started_ms + C300X_CALLER_WAIT_MS;
        }
        return timeout;
    }
    return live(call) ? call->updated_ms + C300X_CALL_ACTIVE_TIMEOUT_MS : -1;
}

void c300x_calls_tick(struct c300x_calls *calls, const struct c300x_call_sink *sink, long long now)
{
    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        struct c300x_call *call = &calls->items[index];
        long long due = deadline(call);
        if (call->state == C300X_CALL_ENDED && now - call->updated_ms >= C300X_CALL_ENDED_KEEP_MS) {
            memset(call, 0, sizeof(*call));
        }
        if (due < 0 || now < due) {
            continue;
        }
        if (call->state == C300X_CALL_RINGING && call->unit[0] == '\0'
            && now - call->started_ms < C300X_CALL_RINGING_TIMEOUT_MS) {
            const struct c300x_outdoor_unit *unit = sink != NULL && sink->units != NULL
                ? c300x_outdoor_units_default(sink->units) : NULL;
            if (unit != NULL) {
                bind_unit(calls, sink, call, unit, "default_fallback", NULL, now);
                continue;
            }
            call->attribution = "default_fallback";
            call->bound_ms = now;
        }
        if (now - call->updated_ms >= (call->state == C300X_CALL_RINGING
                ? C300X_CALL_RINGING_TIMEOUT_MS : C300X_CALL_ACTIVE_TIMEOUT_MS)) {
            c300x_calls_end(calls, sink, call->id, "timeout", now);
        }
    }
}

int c300x_calls_timeout_ms(const struct c300x_calls *calls, long long now)
{
    long long next = -1;

    for (int index = 0; index < C300X_MAX_CALLS; index++) {
        const struct c300x_call *call = &calls->items[index];
        long long due = deadline(call);
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
    const struct c300x_call *answered = newest(mutable_calls, C300X_CALL_ANSWERED, 0);
    return answered != NULL ? answered : newest(mutable_calls, C300X_CALL_RINGING, 0);
}

const struct c300x_call *c300x_calls_live_for_unit(const struct c300x_calls *calls, const char *unit)
{
    struct c300x_calls *mutable_calls = (struct c300x_calls *)calls;
    const struct c300x_call *call = live_for_unit(mutable_calls, unit, 0);
    return call != NULL ? call : live_for_unit(mutable_calls, unit, 1);
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

void c300x_calls_answer_started(struct c300x_calls *calls, const char *call_id)
{
    struct c300x_call *call = (struct c300x_call *)c300x_calls_find(calls, call_id);
    if (call != NULL) {
        call->answer_pending = 1;
    }
}

void c300x_calls_hangup_started(struct c300x_calls *calls, const char *call_id)
{
    struct c300x_call *call = (struct c300x_call *)c300x_calls_find(calls, call_id);
    if (call != NULL) {
        call->hangup_pending = 1;
    }
}

void c300x_calls_action_refused(struct c300x_calls *calls, const char *call_id)
{
    struct c300x_call *call = (struct c300x_call *)c300x_calls_find(calls, call_id);
    if (call != NULL) {
        call->answer_pending = call->hangup_pending = 0;
    }
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
    call->answer_pending = 0;
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

int c300x_calls_json(const struct c300x_calls *calls, long long now, char *out, size_t out_len)
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
                       "\"caller_frames_ignored\":%lu,\"calls\":[", calls->boot_id,
                       current ? "\"" : "null", current ? current->id : "", current ? "\"" : "",
                       calls->caller_frames_ignored)) {
        return 0;
    }
    for (int index = 0; index < count; index++) {
        const struct c300x_call *call = listed[index];
        if (!c300x_appendf(out, out_len, &used,
                "%s{\"call_id\":\"%s\",\"kind\":\"%s\",\"state\":\"%s\",\"unit\":%s,\"attribution\":\"%s\","
                "\"answered_by\":%s%s%s,\"end_reason\":%s%s%s,\"age_ms\":%lld}",
                index > 0 ? "," : "", call->id, call->view ? "view" : "ring", state_name(call->state),
                unit_json(call, unit, sizeof(unit)), call->attribution,
                call->answered_by ? "\"" : "null", call->answered_by ? call->answered_by : "",
                call->answered_by ? "\"" : "",
                call->end_reason ? "\"" : "null", call->end_reason ? call->end_reason : "",
                call->end_reason ? "\"" : "", now - call->started_ms)) {
            return 0;
        }
    }
    return c300x_appendf(out, out_len, &used, "]}\n");
}
