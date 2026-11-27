#ifndef C300X_HTTP_ACTIVATIONS_H
#define C300X_HTTP_ACTIVATIONS_H

#include "activation_discovery.h"
#include "http_request.h"
#include "local_action_events.h"

typedef void (*c300x_activation_emit_fn)(void *context, const char *type, const char *data_json);

/* The activation and stair-light routes. The discovery is the runtime's,
 * read again on every GET /api/v1/activations; units names a lock's
 * outdoor unit. */
struct c300x_activation_routes {
    const struct c300x_config *config;
    struct c300x_activation_discovery *discovery;
    const struct c300x_outdoor_units *units;
    struct c300x_local_action_events *local_events;
    c300x_activation_emit_fn emit;
    void *context;
};

/* Configured items plus the station's (when station items are on). */
int c300x_activations_count(const struct c300x_activation_routes *routes);
/* Zero when the request is not one of these routes. */
int c300x_http_activations_route(int client_fd, const struct c300x_activation_routes *routes,
                                 const struct request *request);

#endif
