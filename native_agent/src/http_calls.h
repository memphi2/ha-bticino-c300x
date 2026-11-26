#ifndef C300X_HTTP_CALLS_H
#define C300X_HTTP_CALLS_H

#include <stddef.h>

#include "call_table.h"
#include "http_request.h"
#include "outdoor_units.h"

struct c300x_config;
struct c300x_video;
struct c300x_video_control;

/* The station's outdoor units and calls, owned by the agent's loop. */
struct c300x_call_hub {
    struct c300x_calls calls;
    struct c300x_outdoor_units units;
    struct c300x_call_sink sink;
    const struct c300x_config *config;
};

void c300x_call_hub_init(struct c300x_call_hub *hub, const struct c300x_config *config,
                         c300x_call_emit_fn emit, void *context);
/* Every bus frame, before it becomes an event. */
void c300x_call_hub_frame(struct c300x_call_hub *hub, const char *frame);
/* Before an event goes out: 0 drop it, 1 send it as it is, 2 send out instead. */
int c300x_call_hub_event(struct c300x_call_hub *hub, const char *type, const char *data,
                         char *out, size_t out_len);
/* doorbell.media.closed as it goes out; station_holds_media: its payload
 * still reports the station's own media (external_media_active). */
void c300x_call_hub_media_closed(struct c300x_call_hub *hub, int station_holds_media);
int c300x_call_hub_timeout_ms(struct c300x_call_hub *hub);
void c300x_call_hub_tick(struct c300x_call_hub *hub);

struct c300x_call_routes {
    struct c300x_call_hub *hub;
    struct c300x_video_control *control;
    struct c300x_video *video;
};

/* Zero when the request is not one of these routes. */
int c300x_http_calls_route(int client_fd, const struct c300x_call_routes *routes, const struct request *request);

#endif
