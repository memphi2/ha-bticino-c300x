#ifndef C300X_CALL_TABLE_H
#define C300X_CALL_TABLE_H

#include <stddef.h>

#include "outdoor_units.h"

#define C300X_MAX_CALLS 8
#define C300X_CALL_ID_LEN 24
#define C300X_RING_REPEAT_MS 1000
#define C300X_CALLER_WAIT_MS 1000
#define C300X_CALLER_BIND_WINDOW_MS 1500
#define C300X_CALL_RINGING_TIMEOUT_MS 90000
#define C300X_CALL_ACTIVE_TIMEOUT_MS (15 * 60 * 1000)
#define C300X_CALL_ENDED_KEEP_MS 60000

enum c300x_call_state {
    C300X_CALL_FREE = 0,
    C300X_CALL_RINGING,
    C300X_CALL_ANSWERED,
    C300X_CALL_VIEWING,
    C300X_CALL_ENDED,
};

struct c300x_call {
    char id[C300X_CALL_ID_LEN];
    enum c300x_call_state state;
    int view;
    char unit[C300X_UNIT_WHERE_LEN]; /* unit id, empty while not known */
    const char *attribution;         /* pending, caller_frame, default_fallback */
    const char *answered_by;         /* NULL, ha, station */
    const char *end_reason;
    int answer_pending;
    int hangup_pending; /* HA's hang-up runs: the media close it causes ends the call as "hangup" */
    long long started_ms;
    long long last_ring_ms;
    long long bound_ms;
    long long updated_ms;
};

/* Calls of one station, owned by the agent's loop. Ring frames carry no
 * caller: the caller frame that follows binds the unit to the call. */
struct c300x_calls {
    char boot_id[12];
    unsigned long seq;
    struct c300x_call items[C300X_MAX_CALLS];
    long long repeat_after_bind_ms; /* a ring copy came after the newest call got its unit */
    unsigned long caller_frames_ignored;
};

/* type and data_json of one event to send; data_json is a JSON object. */
typedef void (*c300x_call_emit_fn)(void *context, const char *type, const char *data_json);

struct c300x_call_sink {
    c300x_call_emit_fn emit;
    void *context;
    struct c300x_outdoor_units *units;
};

/* boot_id NULL or empty: a random one, drawn now (at agent start). */
void c300x_calls_init(struct c300x_calls *calls, const char *boot_id);
/* A ring (bus frame or the ring's INVITE). Returns 1 with the ring event's
 * call fields in data (an object to send as doorbell.pressed), 0 for a repeat. */
int c300x_calls_ring(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                     const char *raw, long long now, char *data, size_t data_len);
/* Caller and view frames: they name the unit of a call. */
void c300x_calls_frame(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                       const char *frame, long long now);
/* The agent saw the ring answered (doorbell.view_requested of the ring):
 * by Home Assistant while its answer runs, else on the station. */
void c300x_calls_answer_seen(struct c300x_calls *calls, const struct c300x_call_sink *sink, long long now);
void c300x_calls_media_closed(struct c300x_calls *calls, const struct c300x_call_sink *sink, long long now);
void c300x_calls_tick(struct c300x_calls *calls, const struct c300x_call_sink *sink, long long now);
/* -1 while no call needs a timer. */
int c300x_calls_timeout_ms(const struct c300x_calls *calls, long long now);

const struct c300x_call *c300x_calls_find(const struct c300x_calls *calls, const char *call_id);
/* The answered call, else the newest ringing one. */
const struct c300x_call *c300x_calls_current(const struct c300x_calls *calls);
const struct c300x_call *c300x_calls_live_for_unit(const struct c300x_calls *calls, const char *unit);
int c300x_calls_is_current(const struct c300x_calls *calls, const char *call_id);
/* Unlock with a call id: that unit's call, live or ended within the keep time. */
int c300x_calls_unlock_allowed(const struct c300x_calls *calls, const char *call_id,
                               const char *unit, long long now);
void c300x_calls_answer_started(struct c300x_calls *calls, const char *call_id);
void c300x_calls_hangup_started(struct c300x_calls *calls, const char *call_id);
/* HA's answer or hang-up was refused: a later answer or close is not HA's. */
void c300x_calls_action_refused(struct c300x_calls *calls, const char *call_id);
void c300x_calls_answered(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                          const char *call_id, const char *by, long long now);
void c300x_calls_end(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                     const char *call_id, const char *reason, long long now);
int c300x_calls_json(const struct c300x_calls *calls, long long now, char *out, size_t out_len);

#endif
