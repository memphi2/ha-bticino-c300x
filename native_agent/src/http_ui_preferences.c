#include "http_ui_preferences.h"
#include "http_auth.h"
#include "http_util.h"
#include "json_util.h"

#include <string.h>

void c300x_http_ui_preferences(int fd, struct c300x_config *config, const struct request *request, int loopback)
{
    if (!loopback) {
        c300x_http_send_json(fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"loopback_required\"}\n");
        return;
    }
    if (strcmp(request->method, "POST") == 0) {
        char header[3];
        int enabled, changed;
        char error[C300X_MAX_ERROR_LEN];
        /* Browsers cannot send this custom header cross-origin without preflight. */
        if (header_value(request, "origin", header, sizeof(header))
            || !header_value(request, "x-c300x-ui", header, sizeof(header))
            || strcmp(header, "1") != 0) {
            c300x_http_send_json(fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"ui_header_required\"}\n");
            return;
        }
        if (!c300x_json_bool_field(request->body, "feedback_enabled", &enabled)) {
            c300x_http_send_json(fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_feedback_enabled\"}\n");
            return;
        }
        if (!c300x_save_display_feedback(config, enabled, error, sizeof(error), &changed)) {
            c300x_http_send_json(fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"config_save_failed\"}\n");
            return;
        }
    } else if (strcmp(request->method, "GET") != 0) {
        c300x_http_send_json(fd, 405, "Method Not Allowed", "{\"ok\":false,\"error\":\"method_not_allowed\"}\n");
        return;
    }
    c300x_http_send_json(fd, 200, "OK", config->display_feedback_enabled
        ? "{\"ok\":true,\"feedback_enabled\":true}\n"
        : "{\"ok\":true,\"feedback_enabled\":false}\n");
}
