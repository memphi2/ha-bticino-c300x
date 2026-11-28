#ifndef C300X_HTTP_CALLS_H
#define C300X_HTTP_CALLS_H

#include <stddef.h>

#include "call_table.h"
#include "door_contact.h"
#include "http_request.h"
#include "outdoor_units.h"

struct c300x_config;
struct c300x_video;
struct c300x_video_control;

/* The station's outdoor units and calls, owned by the agent's loop. */
/* What an unlock resolved for the command it sent. Only the request that
 * owns the OpenWebNet worker runs again, so one is enough; it is stored
 * when that request's command starts, never by a request that waits. */
struct c300x_unlock_resolved {
    char unit[C300X_UNIT_WHERE_LEN];
    char lock_where[C300X_UNIT_WHERE_LEN];
    char call_id[33];
};

struct c300x_call_hub {
    struct c300x_calls calls;
    struct c300x_outdoor_units units;
    struct c300x_call_sink sink;
    c300x_call_emit_fn emit;
    void *context;
    const struct c300x_config *config;
    struct c300x_video *const *video;
    const struct c300x_video_control *control;
    struct c300x_unlock_resolved unlock;
    int stopping; /* HA's hang-up or stop runs in its handler right now */
    char seen_path[C300X_UNIT_PATH_LEN]; /* empty: seen units are not kept */
    struct c300x_door_contacts doors;
    char doors_path[C300X_UNIT_PATH_LEN]; /* empty: door contacts are not kept */
    int seen_loaded;
    int station_asked; /* the station was asked for its call state */
};

void c300x_call_hub_init(struct c300x_call_hub *hub, const struct c300x_config *config,
                         c300x_call_emit_fn emit, void *context);
/* Where the hub reads the agent's media state from. */
void c300x_call_hub_bind(struct c300x_call_hub *hub, struct c300x_video *const *video,
                         const struct c300x_video_control *control);
/* Every bus frame, before it becomes an event. */
void c300x_call_hub_frame(struct c300x_call_hub *hub, const char *frame);
/* Before an event goes out: 1 send it as it is, 2 send out instead. A ring
 * reaches it only once the duplicate filter let it through. */
int c300x_call_hub_event(struct c300x_call_hub *hub, const char *type, const char *data,
                         char *out, size_t out_len);
/* doorbell.media.closed as it goes out; station_holds_media: its payload
 * still reports the station's own media (external_media_active); from_bus:
 * a bus end frame, not the close of the agent's own leg. */
void c300x_call_hub_media_closed(struct c300x_call_hub *hub, int station_holds_media, int from_bus);
int c300x_call_hub_timeout_ms(struct c300x_call_hub *hub);
void c300x_call_hub_tick(struct c300x_call_hub *hub);

struct c300x_openwebnet_async;

struct c300x_call_routes {
    struct c300x_call_hub *hub;
    struct c300x_video_control *control;
    struct c300x_video *video;
    struct c300x_openwebnet_async *openwebnet; /* NULL: OpenWebNet runs in place */
};

/* Zero when the request is not one of these routes. */
int c300x_http_calls_route(int client_fd, const struct c300x_call_routes *routes, const struct request *request);

#endif
