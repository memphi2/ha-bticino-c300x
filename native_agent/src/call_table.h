#ifndef C300X_CALL_TABLE_H
#define C300X_CALL_TABLE_H

#include <stddef.h>

#include "outdoor_units.h"
#include "station_state.h"

#define C300X_MAX_CALLS 8
#define C300X_CALL_ID_LEN 24
/* No caller frame by then: the default unit is the caller. */
#define C300X_CALLER_WAIT_MS 1000
/* A ring's media close waits this long for the answer frame of the display
 * or the app, which can come after it. */
#define C300X_CALL_SETTLE_MS 1500
#define C300X_CALL_RINGING_TIMEOUT_MS 90000
/* An answered call is checked against the media state once the station's
 * conversation timer (60 s) and the agent's display guard (65 s) are over,
 * and every few seconds after that; a view from its start on. */
#define C300X_CALL_GUARD_MS 66000
#define C300X_CALL_PROBE_MS 5000
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
    const char *closing;             /* ringing: its media closed, the end it gets without an answer */
    long long started_ms;
    long long closed_ms;
    long long probe_ms;
    long long updated_ms;
};

/* The calls mirror the agent's ring session: a ring the duplicate filter
 * lets through starts one, the ring and media events answer and end it.
 * The caller frame only names its unit. */
struct c300x_calls {
    char boot_id[12];
    unsigned long seq;
    struct c300x_call items[C300X_MAX_CALLS];
    unsigned long caller_frames_ignored;
    int station_state;   /* *#8**35, C300X_STATION_STATE_UNKNOWN until one is seen */
    long long station_ms;
    long long idle_ms;   /* the station went idle then; -1 while it is not */
};

/* What the agent's media state says now. */
struct c300x_call_media {
    int ring_leg;    /* the agent's ring leg is up */
    int ha_answered; /* Home Assistant answered that leg or is answering it */
    int external;    /* the display or the app holds the media (display guard included) */
    int agent;       /* the agent's own on-demand media */
    int ha_hangup;   /* Home Assistant's hang-up or stop runs */
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
/* A ring the duplicate filter let through: the live ring call, else a new one. */
const struct c300x_call *c300x_calls_ring(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                                          long long now);
/* Caller and view frames: they name the unit of a call. */
void c300x_calls_frame(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                       const char *frame, long long now);
/* The station's call state (*#8**35, repeats ignored): its conversation or
 * its answering machine answers the ringing call, the conversation not while
 * the agent's own on-demand view runs without its ring leg (that view
 * reports it too); once it is idle, a call
 * that was live then and that no media close ended within the settle time
 * ends with station_idle. */
void c300x_calls_station(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                         const struct c300x_call_media *media, int code, long long now);
/* The ring was answered (doorbell.view_requested of the ring). */
void c300x_calls_answer_seen(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                             const struct c300x_call_media *media, long long now);
/* doorbell.media.closed as it goes out, of a view's media (view) or of the
 * ring's: it belongs to those calls only. external: its payload still
 * reports the station's media; from_bus: a bus end frame, not the agent's
 * own media. */
void c300x_calls_media_closed(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                              const struct c300x_call_media *media, int view, int external, int from_bus,
                              long long now);
void c300x_calls_tick(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                      const struct c300x_call_media *media, long long now);
/* -1 while no call needs a timer. */
int c300x_calls_timeout_ms(const struct c300x_calls *calls, long long now);

const struct c300x_call *c300x_calls_find(const struct c300x_calls *calls, const char *call_id);
/* The live ring call, else the newest view. */
const struct c300x_call *c300x_calls_current(const struct c300x_calls *calls);
/* The live call a media close of the ring (view 0) or of a view (view 1)
 * belongs to: the ring call, the newest view; NULL when none is live. */
const struct c300x_call *c300x_calls_media_call(const struct c300x_calls *calls, int view);
const struct c300x_call *c300x_calls_live_for_unit(const struct c300x_calls *calls, const char *unit);
int c300x_calls_is_current(const struct c300x_calls *calls, const char *call_id);
/* Unlock with a call id: that unit's call, live or ended within the keep time. */
int c300x_calls_unlock_allowed(const struct c300x_calls *calls, const char *call_id,
                               const char *unit, long long now);
/* NULL when Home Assistant's hang-up can end this call, else the error that
 * refuses it: the agent holds no leg of the call. station_busy: the station
 * or its answering machine answered it, or the display or the app holds the
 * view; ring_call_not_active: it rings without the agent's ring leg. */
const char *c300x_calls_hangup_refusal(const struct c300x_call *call, const struct c300x_call_media *media);
void c300x_calls_answered(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                          const char *call_id, const char *by, long long now);
void c300x_calls_end(struct c300x_calls *calls, const struct c300x_call_sink *sink,
                     const char *call_id, const char *reason, long long now);
/* media: what the agent's media state says now, for each call's can_hangup. */
int c300x_calls_json(const struct c300x_calls *calls, const struct c300x_call_media *media, long long now,
                     char *out, size_t out_len);

#endif
