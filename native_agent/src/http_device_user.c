#include "http_device_user.h"
#include "c300x_agent.h"
#include "device_detect.h"
#include "device_routing.h"
#include "device_user.h"
#include "device_user_label.h"
#include "http_util.h"
#include "json_util.h"
#include "string_util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define C300X_DEVICE_USER_STATUS_BODY_LEN 8192

enum device_user_phase { USER_STATUS, USER_ENSURE, USER_RESTORE };

struct device_user_request {
    const struct c300x_config *config;
    struct c300x_device_user_status status;
    struct c300x_device_routing_status routing;
    int restoring;
    char output[C300X_DEVICE_USER_STATUS_BODY_LEN];
};

static void device_user_status_body(
    const struct c300x_device_routing_status *routing,
    char *qml_output,
    int qml_ok,
    const struct c300x_device_user_status *status,
    char *body,
    size_t body_len
)
{
    const struct c300x_device_routing_status routing_status = *routing;
    char qml_state[32] = "unknown";
    int qml_patched = 0;
    int qml_available = 0;
    char error_json[C300X_JSON_QUOTED_LEN(C300X_DEVICE_USER_ERROR_LEN)];
    char account_label_json[C300X_JSON_QUOTED_LEN(C300X_DEVICE_USER_LABEL_LEN)];
    char routing_state_json[C300X_JSON_QUOTED_LEN(C300X_DEVICE_ROUTING_STATE_LEN)];
    char routing_error_json[C300X_JSON_QUOTED_LEN(C300X_DEVICE_ROUTING_ERROR_LEN)];
    char qml_state_json[C300X_JSON_QUOTED_LEN(sizeof(qml_state))];

    if (qml_ok) {
        char *start = (char *)c300x_label_trim(qml_output);
        if (start[0] == '{') {
            qml_available = 1;
            c300x_json_string_field(start, "media_user_label_state", qml_state, sizeof(qml_state));
            if (qml_state[0] == '\0') {
                c300x_copy_string(qml_state, sizeof(qml_state), "unknown");
            }
            if (!c300x_json_bool_field(start, "media_user_label_patched", &qml_patched)) {
                qml_patched = 0;
            }
        }
    }
    c300x_json_string(status->error, error_json, sizeof(error_json));
    c300x_json_string(status->account_label, account_label_json, sizeof(account_label_json));
    c300x_json_string(routing_status.state, routing_state_json, sizeof(routing_state_json));
    c300x_json_string(routing_status.error, routing_error_json, sizeof(routing_error_json));
    c300x_json_string(qml_state, qml_state_json, sizeof(qml_state_json));
    snprintf(
        body,
        body_len,
        "{"
        "\"ok\":%s,"
        "\"status_available\":%s,"
        "\"supported\":%s,"
        "\"domain_present\":%s,"
        "\"device_user_present\":%s,"
        "\"homeassistant_user_present\":%s,"
        "\"accounts_homeassistant_present\":%s,"
        "\"route_int_homeassistant_present\":%s,"
        "\"route_ext_homeassistant_present\":%s,"
        "\"route_conf_homeassistant_present\":%s,"
        "\"route_conf_is_symlink\":%s,"
        "\"writable_files_present\":%s,"
        "\"media_identity_available\":%s,"
        "\"routes_consistent\":%s,"
        "\"device_routing_supported\":%s,"
        "\"device_routing_applied\":%s,"
        "\"device_routing_state\":%s,"
        "\"device_routing_backup_present\":%s,"
        "\"device_routing_error\":%s,"
        "\"root_writable\":%s,"
        "\"media_user_label_available\":%s,"
        "\"media_user_label_applied\":%s,"
        "\"media_user_label_state\":%s,"
        "\"account_label\":%s,"
        "\"error\":%s"
        "}\n",
        status->status_available ? "true" : "false",
        status->status_available ? "true" : "false",
        status->supported ? "true" : "false",
        status->domain_present ? "true" : "false",
        status->device_user_present ? "true" : "false",
        status->homeassistant_user_present ? "true" : "false",
        status->accounts_homeassistant_present ? "true" : "false",
        status->route_int_homeassistant_present ? "true" : "false",
        status->route_ext_homeassistant_present ? "true" : "false",
        status->route_conf_homeassistant_present ? "true" : "false",
        status->route_conf_is_symlink ? "true" : "false",
        status->writable_files_present ? "true" : "false",
        status->media_identity_available ? "true" : "false",
        status->routes_consistent ? "true" : "false",
        routing_status.supported ? "true" : "false",
        routing_status.patched ? "true" : "false",
        routing_state_json,
        routing_status.backup_present ? "true" : "false",
        routing_error_json,
        routing_status.root_writable ? "true" : "false",
        qml_available ? "true" : "false",
        qml_patched ? "true" : "false",
        qml_state_json,
        account_label_json,
        error_json
    );
}

static void send_status(int fd, struct device_user_request *state, int qml_ok)
{
    char body[C300X_DEVICE_USER_STATUS_BODY_LEN];
    device_user_status_body(&state->routing, state->output, qml_ok, &state->status,
        body, sizeof(body));
    c300x_http_send_json(fd, 200, "OK", body);
}

static void send_error(int fd, const char *error, const char *detail)
{
    char body[C300X_DEVICE_USER_STATUS_BODY_LEN];
    char quoted[C300X_JSON_QUOTED_LEN(C300X_DEVICE_USER_ERROR_LEN)];
    if (detail != NULL) {
        c300x_json_string(detail, quoted, sizeof(quoted));
        snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\",\"detail\":%s}\n", error, quoted);
    } else {
        snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}\n", error);
    }
    c300x_http_send_json(fd, 500, "Internal Server Error", body);
}

static int finish_device_user(struct c300x_http_maintenance *owner)
{
    struct device_user_request *state = owner->context;
    send_status(owner->client_fd, state, !owner->job.failed);
    return 1;
}

static int start_status(struct c300x_http_maintenance *owner, int fd,
    struct device_user_request *state)
{
    owner->complete = finish_device_user;
    /* A write of this request that left / writable is reported with it. */
    int root_writable = state->routing.root_writable;
    (void)c300x_device_user_read_status(&state->status);
    memset(&state->routing, 0, sizeof(state->routing));
    (void)c300x_device_routing_read_status(&state->routing);
    state->routing.root_writable = root_writable;
    if (c300x_device_display_files_patchable()
        && access(state->config->maintenance_qml_patch_script, X_OK) == 0
        && c300x_command_job_start_capture(&owner->job,
            state->config->maintenance_qml_patch_script, "status", state->output, 4096, 10000)) {
        return 1;
    }
    /* A missing/failed status script never makes device-user GET fail. */
    send_status(fd, state, 0);
    return 0;
}

static int restore_routing(struct c300x_http_maintenance *owner, int fd,
    struct device_user_request *state)
{
    char error[C300X_DEVICE_USER_ERROR_LEN] = "";
    if (!c300x_device_routing_restore(&state->routing, error, sizeof(error))) {
        send_error(fd, "device_routing_restore_failed", error);
        return 0;
    }
    owner->record_write(owner->write_context, "device_user", "restore_homeassistant_media_user_setup");
    return start_status(owner, fd, state);
}

/* The label is a QML write: the same job, deadline and grace period, so the
 * script's trap rolls back instead of a kill, and the main loop never waits. */
static int finish_label(struct c300x_http_maintenance *owner)
{
    struct device_user_request *state = owner->context;
    int fd = owner->client_fd;
    if (owner->job.failed && owner->job.timed_out) {
        c300x_label_send_timeout(fd, owner->job.exit_status);
        return 1;
    }
    /* The script can exit zero and still report that it rolled back. */
    if (owner->job.failed || !c300x_label_result_ok(state->output, !state->restoring)) {
        send_error(fd, state->restoring ? "media_user_label_restore_failed"
            : "media_user_label_setup_failed", NULL);
        return 1;
    }
    if (state->restoring) {
        return !restore_routing(owner, fd, state);
    }
    owner->record_write(owner->write_context, "device_user", "ensure_homeassistant_user");
    return !start_status(owner, fd, state);
}

static int start_label(struct c300x_http_maintenance *owner, struct device_user_request *state,
    int restoring)
{
    state->restoring = restoring;
    if (!c300x_label_job_start(&owner->job, state->config->maintenance_qml_patch_script,
            restoring, state->output, sizeof(state->output))) {
        return 0;
    }
    owner->complete = finish_label;
    return 1;
}

static int ensure_user(struct c300x_http_maintenance *owner, int fd,
    struct device_user_request *state, const struct request *request)
{
    char error[C300X_DEVICE_USER_ERROR_LEN] = "";
    char account_label[C300X_DEVICE_USER_LABEL_LEN] = "";
    c300x_json_string_field(request->body, "account_label", account_label, sizeof(account_label));
    /* Reject unknown active-route ownership before patching vendor files. */
    if (!c300x_device_user_read_status(&state->status) || !state->status.supported) {
        send_error(fd, "device_user_update_failed", state->status.error);
        return 0;
    }
    struct c300x_device_routing_status before;
    memset(&before, 0, sizeof(before));
    (void)c300x_device_routing_read_status(&before);
    if (!c300x_device_routing_apply(&state->routing, error, sizeof(error))) {
        send_error(fd, "device_routing_failed", error);
        return 0;
    }
    if (!c300x_device_user_ensure_homeassistant(&state->status, account_label, error, sizeof(error))) {
        /* No HA user: do not leave the vendor routing patched for it. */
        if (!before.patched) {
            char ignored[C300X_DEVICE_USER_ERROR_LEN];
            (void)c300x_device_routing_restore(&before, ignored, sizeof(ignored));
        }
        send_error(fd, "device_user_update_failed", error);
        return 0;
    }
    /* The label is written into the display's QML files. Without files the
     * patch can edit, user and routing are set up, only the label is not shown. */
    if (c300x_device_display_files_patchable()) {
        if (start_label(owner, state, 0)) {
            return 1;
        }
        send_error(fd, "media_user_label_setup_failed", NULL);
        return 0;
    }
    owner->record_write(owner->write_context, "device_user", "ensure_homeassistant_user");
    return start_status(owner, fd, state);
}

int c300x_http_device_user_route(struct c300x_http_maintenance *owner, int client_fd,
    const struct c300x_config *config, const struct request *request)
{
    enum device_user_phase phase;
    int pending;
    const char *confirmation = NULL;
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/device-user") == 0) {
        phase = USER_STATUS;
    } else if (strcmp(request->method, "POST") == 0
        && strcmp(request->path, "/api/v1/maintenance/device-user/actions/ensure-homeassistant") == 0) {
        phase = USER_ENSURE;
        confirmation = "ensure_homeassistant_user";
    } else if (strcmp(request->method, "POST") == 0
        && strcmp(request->path, "/api/v1/maintenance/device-user/actions/restore-homeassistant-setup") == 0) {
        phase = USER_RESTORE;
        confirmation = "restore_ha_user_setup";
    } else {
        return 0;
    }
    if (confirmation != NULL && !maintenance_authorized(config, request)) {
        c300x_http_send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return 1;
    }
    if (c300x_http_maintenance_busy(owner)) {
        c300x_http_send_json(client_fd, 409, "Conflict", "{\"ok\":false,\"error\":\"maintenance_busy\"}\n");
        return 1;
    }
    if (confirmation != NULL && !confirm_matches(request, confirmation)) {
        c300x_http_send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return 1;
    }
    struct device_user_request *state = calloc(1, sizeof(*state));
    if (state == NULL) {
        c300x_http_send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        return 1;
    }
    state->config = config;
    if (phase == USER_STATUS) {
        pending = start_status(owner, client_fd, state);
    } else if (phase == USER_ENSURE) {
        pending = ensure_user(owner, client_fd, state, request);
    } else if (!c300x_device_display_files_patchable()
        || access(config->maintenance_qml_patch_script, X_OK) != 0) {
        pending = restore_routing(owner, client_fd, state);
    } else if (!(pending = start_label(owner, state, 1))) {
        send_error(client_fd, "media_user_label_restore_failed", NULL);
    }
    if (pending) {
        owner->client_fd = client_fd;
        owner->context = state;
        owner->destroy_context = free;
    } else {
        owner->complete = NULL;
        free(state);
    }
    return 1;
}
