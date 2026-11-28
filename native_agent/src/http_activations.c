#include "http_activations.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "activations.h"
#include "http_calls.h"
#include "http_util.h"
#include "json_util.h"
#include "openwebnet_call.h"
#include "string_util.h"
#include "time_util.h"

#define ACTIVATIONS_PREFIX "/api/v1/activations/"
#define RUN_SUFFIX "/actions/run"

/* A request whose bus command runs on the worker is answered when it runs again. */
static void reply(int client_fd, int status, const char *reason, const char *body)
{
    if (!c300x_openwebnet_deferred()) {
        c300x_http_send_json(client_fd, status, reason, body);
    }
}

static void reply_bus_error(int client_fd, const char *error)
{
    char body[2048];
    char error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];

    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":%s}\n", c300x_json_string(error, error_json, sizeof(error_json)));
    reply(client_fd, 502, "Bad Gateway", body);
}

static int address_valid(const char *value)
{
    size_t len = strlen(value);

    if (len == 0 || len >= C300X_MAX_ADDRESS_LEN) {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        if (!isdigit((unsigned char)value[index]) && value[index] != '#') {
            return 0;
        }
    }
    return 1;
}

static const struct c300x_activation_discovery *discovery(const struct c300x_activation_routes *routes)
{
    if (!routes->discovery->loaded) {
        c300x_activation_discover(routes->config, routes->discovery);
    }
    return routes->discovery;
}

int c300x_activations_count(const struct c300x_activation_routes *routes)
{
    if (!routes->config->activations_enabled) {
        return 0;
    }
    return routes->config->activations_count + discovery(routes)->count;
}

static const struct c300x_activation *find_activation(const struct c300x_activation_routes *routes, const char *id)
{
    const struct c300x_activation_discovery *station = discovery(routes);

    for (int index = 0; index < routes->config->activations_count; index++) {
        if (strcmp(routes->config->activations[index].id, id) == 0) {
            return &routes->config->activations[index];
        }
    }
    for (int index = 0; index < station->count; index++) {
        if (strcmp(station->items[index].id, id) == 0) {
            return &station->items[index];
        }
    }
    return NULL;
}

static void activations_get(int client_fd, const struct c300x_activation_routes *routes)
{
    char *body = malloc(C300X_ACTIVATIONS_JSON_SIZE);

    if (body == NULL) {
        c300x_http_send_json(client_fd, 503, "Service Unavailable", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        return;
    }
    /* The station's files are read again: an installer may have changed them. */
    c300x_activation_discover(routes->config, routes->discovery);
    const struct c300x_outdoor_units *units = routes->calls != NULL ? c300x_call_hub_load_units(routes->calls) : NULL;
    if (!c300x_activations_json(routes->config, routes->discovery, units, body, C300X_ACTIVATIONS_JSON_SIZE)) {
        c300x_http_send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
    } else {
        c300x_http_send_json(client_fd, 200, "OK", body);
    }
    free(body);
}

static void emit(const struct c300x_activation_routes *routes, const char *type, const char *data)
{
    if (routes->emit != NULL) {
        routes->emit(routes->context, type, data);
    }
}

/* The bus echo of the agent's own frame is not reported a second time. */
static void remember(const struct c300x_activation_routes *routes, const char *type, const char *address)
{
    if (routes->local_events != NULL) {
        c300x_local_action_event_remember(routes->local_events, type, address, c300x_monotonic_ms());
    }
}

static void lock_event(const struct c300x_activation_routes *routes, const struct c300x_activation *activation,
                       const char *type, const char *raw)
{
    char raw_json[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN)];
    char address_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ADDRESS_LEN)];
    char id_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ACTIVATION_ID_LEN)];
    char data[2048];

    remember(routes, type, activation->address);
    if (snprintf(data, sizeof(data), "{\"raw\":%s,\"address\":%s,\"source\":\"activation\",\"activation_id\":%s}",
                 c300x_json_string(raw, raw_json, sizeof(raw_json)),
                 c300x_json_string(activation->address, address_json, sizeof(address_json)),
                 c300x_json_string(activation->id, id_json, sizeof(id_json))) < (int)sizeof(data)) {
        emit(routes, type, data);
    }
}

static void activation_run(int client_fd, const struct c300x_activation_routes *routes, const char *id)
{
    const struct c300x_config *config = routes->config;
    const struct c300x_activation *activation;
    char press[C300X_MAX_FRAME_LEN];
    char release[C300X_MAX_FRAME_LEN];
    char reply_frame[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    char id_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ACTIVATION_ID_LEN)];
    char name_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ACTIVATION_NAME_LEN)];
    char type_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ACTIVATION_TYPE_LEN)];
    char data[1024];
    char body[sizeof(data) + 16];
    int sent;

    if (!config->activations_enabled) {
        reply(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"activations_disabled\"}\n");
        return;
    }
    activation = find_activation(routes, id);
    if (activation == NULL) {
        reply(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"unknown_activation\"}\n");
        return;
    }
    c300x_activation_press_release_commands(activation, press, sizeof(press), release, sizeof(release));
    if (!c300x_activation_is_executable(activation) || press[0] == '\0') {
        reply(client_fd, 405, "Method Not Allowed", "{\"ok\":false,\"error\":\"activation_not_executable\"}\n");
        return;
    }
    sent = release[0] != '\0'
        ? c300x_openwebnet_sequence(config, press, c300x_activation_hold_ms(activation, config->lock_release_delay_ms),
                                    release, error, sizeof(error))
        : c300x_openwebnet_send(config, press, reply_frame, sizeof(reply_frame), error, sizeof(error));
    if (!sent) {
        reply_bus_error(client_fd, error);
        return;
    }
    if (strcmp(activation->type, "lock") == 0 && activation->address[0] != '\0') {
        lock_event(routes, activation, "door_unlock.started", press);
        if (release[0] != '\0') {
            lock_event(routes, activation, "door_unlock.ended", release);
        }
    }
    snprintf(data, sizeof(data), "{\"id\":%s,\"name\":%s,\"type\":%s}",
             c300x_json_string(activation->id, id_json, sizeof(id_json)),
             c300x_json_string(activation->name, name_json, sizeof(name_json)),
             c300x_json_string(activation->type, type_json, sizeof(type_json)));
    emit(routes, "activation.executed", data);
    snprintf(body, sizeof(body), "{\"ok\":true,%s\n", data + 1);
    reply(client_fd, 200, "OK", body);
}

/* Press, and release 100 ms later as the display does, on one bus session:
 * an agent stop finishes it (the release goes out), nothing is kept. */
static void stair_light(int client_fd, const struct c300x_activation_routes *routes, const struct request *request)
{
    char address[C300X_MAX_ADDRESS_LEN];
    char press[C300X_MAX_FRAME_LEN];
    char release[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    char address_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ADDRESS_LEN)];
    char body[256];

    if (c300x_json_string_field_checked(request->body, "address", address, sizeof(address)) < 0) {
        reply(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_stair_light_address\"}\n");
        return;
    }
    if (address[0] == '\0') {
        c300x_copy_string(address, sizeof(address), routes->config->stair_light_default_address);
    }
    /* Not configured: the station's own address, as its display does. */
    if (address[0] == '\0' && !c300x_station_own_where(C300X_CONF_XML_PATH, address, sizeof(address))) {
        reply(client_fd, 503, "Service Unavailable", "{\"ok\":false,\"error\":\"stair_light_address_unknown\"}\n");
        return;
    }
    if (!address_valid(address)) {
        reply(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_stair_light_address\"}\n");
        return;
    }
    c300x_stair_light_commands(address, press, sizeof(press), release, sizeof(release));
    if (!c300x_openwebnet_sequence(routes->config, press, C300X_STAIR_LIGHT_RELEASE_MS, release, error, sizeof(error))) {
        reply_bus_error(client_fd, error);
        return;
    }
    snprintf(body, sizeof(body), "{\"ok\":true,\"address\":%s}\n",
             c300x_json_string(address, address_json, sizeof(address_json)));
    reply(client_fd, 200, "OK", body);
}

int c300x_http_activations_route(int client_fd, const struct c300x_activation_routes *routes,
                                 const struct request *request)
{
    int post = strcmp(request->method, "POST") == 0;
    size_t prefix_len = strlen(ACTIVATIONS_PREFIX);
    size_t length = strlen(request->path);

    if (post && strcmp(request->path, "/api/v1/stair-light/actions/activate") == 0) {
        stair_light(client_fd, routes, request);
        return 1;
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/activations") == 0) {
        activations_get(client_fd, routes);
        return 1;
    }
    if (post && length > prefix_len + strlen(RUN_SUFFIX) && strncmp(request->path, ACTIVATIONS_PREFIX, prefix_len) == 0
        && strcmp(request->path + length - strlen(RUN_SUFFIX), RUN_SUFFIX) == 0) {
        char id[C300X_MAX_ACTIVATION_ID_LEN];
        size_t id_len = length - prefix_len - strlen(RUN_SUFFIX);
        if (id_len >= sizeof(id)) {
            c300x_http_send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_activation_id\"}\n");
            return 1;
        }
        percent_decode_query_value(request->path + prefix_len, request->path + prefix_len + id_len, id, sizeof(id));
        activation_run(client_fd, routes, id);
        return 1;
    }
    return 0;
}
