#include "http_service_dispatch.h"
#include "gui_peer.h"
#include "http_util.h"

#include <stdio.h>
#include <string.h>

int c300x_http_service_commands_defer(const struct c300x_http_maintenance *owner,
    const struct c300x_config *config, const struct request *request)
{
    return c300x_http_maintenance_busy(owner)
        && strcmp(request->method, "GET") == 0
        && strcmp(request->path, "/api/v1/maintenance/ssh") == 0
        && api_request_authorized(config, request)
        && maintenance_authorized(config, request) && config->maintenance_ssh_start_enabled;
}

int c300x_http_service_commands_route(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, const struct request *request, c300x_schedule_command_fn schedule)
{
    return c300x_service_dispatch(0, owner, fd, config, request, schedule);
}

int c300x_display_maintenance(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, struct request *request, c300x_schedule_command_fn schedule)
{
    char header[16];
    if (!config->maintenance_enabled || header_value(request, "origin", header, sizeof(header))
        || !header_value(request, "x-c300x-ui", header, sizeof(header)) || strcmp(header, "settings-v1")
        || !c300x_stock_gui_peer(fd)) {
        c300x_http_send_json(fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"display_maintenance_denied\"}\n");
        return 1;
    }
    if (c300x_http_maintenance_busy(owner)) {
        c300x_http_send_json(fd, 409, "Conflict", "{\"ok\":false,\"error\":\"maintenance_busy\"}\n");
        return 1;
    }
    if (!strcmp(request->path, "/ui/maintenance") && !strcmp(request->method, "GET")) {
        char body[96];
        snprintf(body, sizeof(body), "{\"ok\":true,\"ssh\":%s,\"reboot\":%s,\"remove\":%s}\n",
                 config->maintenance_ssh_start_enabled ? "true" : "false",
                 config->maintenance_reboot_enabled ? "true" : "false",
                 config->maintenance_agent_remove_enabled ? "true" : "false");
        c300x_http_send_json(fd, 200, "OK", body);
        return 1;
    }
    const char *path = !strcmp(request->path, "/ui/maintenance/ssh") ? "/api/v1/maintenance/ssh"
        : !strcmp(request->path, "/ui/maintenance/reboot") ? "/api/v1/maintenance/reboot"
        : !strcmp(request->path, "/ui/maintenance/remove") ? "/api/v1/maintenance/agent/actions/remove" : NULL;
    if (path) {
        snprintf(request->path, sizeof(request->path), "%s", path);
        if (c300x_service_dispatch(1, owner, fd, config, request, schedule)) return owner->client_fd != fd;
    }
    c300x_http_send_json(fd, 404, "Not Found", "{\"ok\":false,\"error\":\"unknown_display_action\"}\n");
    return 1;
}
