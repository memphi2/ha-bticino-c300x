#include "http_c100x_display.h"
#include "http_auth.h"
#include "http_util.h"

#include <stdio.h>
#include <string.h>

void c100x_display_capability(const struct c100x_activation *activation, char *out, size_t out_len)
{
    static const char key[] = ",\"c100x_display\":";
    const size_t key_len = sizeof(key) - 1;
    out[0] = '\0';
    if (activation->enabled && out_len > sizeof(key)) {
        memcpy(out, key, sizeof(key));
        if (!c100x_activation_json(activation, &out[key_len], out_len - key_len)) {
            out[0] = '\0';
        }
    }
}

static int reply(int fd, int status, const char *reason, const char *error)
{
    char body[96];
    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}\n", error);
    c300x_http_send_json(fd, status, reason, body);
    return 1;
}

int c100x_display_route(struct c100x_activation *activation, int fd, const struct c300x_config *config,
    const struct request *request)
{
    static const char root[] = "/api/v1/maintenance/c100x-display";
    const size_t root_len = sizeof(root) - 1;
    char body[768];
    const char *action = NULL, *confirmation = NULL, *error, *rest;
    int restore;

    if (!activation->enabled || strncmp(request->path, root, root_len) != 0) {
        return 0;
    }
    rest = &request->path[root_len];
    if (!strcmp(request->method, "GET") && !strcmp(rest, "")) {
        action = "status";
    } else if (!strcmp(request->method, "POST") && !strcmp(rest, "/actions/activate")) {
        action = "activate";
        confirmation = "activate_c100x_display";
    } else if (!strcmp(request->method, "POST") && !strcmp(rest, "/actions/restore")) {
        action = "restore";
        confirmation = "restore_c100x_display";
    } else {
        return 0;
    }
    if (!maintenance_authorized(config, request)) {
        return reply(fd, 403, "Forbidden", "maintenance_unauthorized");
    }
    if (!maintenance_auth_available(config) || !config->maintenance_reboot_enabled) {
        return reply(fd, 404, "Not Found", "maintenance_disabled");
    }
    if (confirmation == NULL) {
        (void)c100x_activation_request(activation, C100X_ACTION_STATUS);
    } else if (!confirm_matches(request, confirmation)) {
        return reply(fd, 400, "Bad Request", "maintenance_confirmation_required");
    } else if ((restore = !strcmp(action, "restore")) == 0 && config->ui_port != 8090) {
        /* The display adapter reaches the agent on 8090 only. */
        return reply(fd, 409, "Conflict", "c100x_display_ui_port_unsupported");
    } else if (restore && activation->known && activation->phase == C100X_PHASE_STOCK) {
        c300x_http_send_json(fd, 200, "OK", "{\"ok\":true,\"action\":\"restore\",\"changed\":false}\n");
        return 1;
    } else if ((error = c100x_activation_request(activation, restore ? C100X_ACTION_RESTORE : C100X_ACTION_PREPARE))
               != NULL) {
        return !strcmp(error, "c100x_display_status_unknown") ? reply(fd, 503, "Service Unavailable", error)
            : reply(fd, 409, "Conflict", error);
    } else {
        snprintf(body, sizeof(body), "{\"ok\":true,\"action\":\"%s\",\"scheduled\":true}\n", action);
        c300x_http_send_json(fd, 202, "Accepted", body);
        return 1;
    }
    memcpy(body, "{\"ok\":true,\"c100x_display\":", 27);
    if (!c100x_activation_json(activation, body + 27, sizeof(body) - 30)) {
        return reply(fd, 500, "Internal Server Error", "c100x_display_status_too_large");
    }
    strcat(body, "}\n");
    c300x_http_send_json(fd, 200, "OK", body);
    return 1;
}
