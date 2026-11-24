#include "http_maintenance.h"
#include "http_util.h"
#include "json_util.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

void c300x_http_maintenance_init(struct c300x_http_maintenance *owner,
    c300x_maintenance_write_fn record_write, void *context)
{
    memset(owner, 0, sizeof(*owner));
    c300x_command_job_init(&owner->job);
    owner->client_fd = -1;
    owner->record_write = record_write;
    owner->write_context = context;
}

int c300x_http_maintenance_busy(const struct c300x_http_maintenance *owner)
{
    return owner->job.pid > 0 || owner->client_fd >= 0;
}

int c300x_http_maintenance_prepare(const struct c300x_http_maintenance *owner, struct pollfd *fd)
{
    return c300x_command_job_prepare(&owner->job, fd);
}

static void release_request(struct c300x_http_maintenance *owner)
{
    if (owner->client_fd >= 0) {
        close_agent_socket(owner->client_fd);
        owner->client_fd = -1;
    }
    if (owner->destroy_context != NULL) {
        owner->destroy_context(owner->context);
    }
    owner->context = NULL;
    owner->destroy_context = NULL;
    owner->complete = NULL;
}

void c300x_http_maintenance_tick(struct c300x_http_maintenance *owner)
{
    c300x_command_job_tick(&owner->job);
    /* Keep the slot through reap, including when the child closed stdout.
     * A completion may start the next phase, never a second concurrent job. */
    if (owner->client_fd >= 0 && owner->job.complete && owner->job.pid == 0
        && owner->complete != NULL && owner->complete(owner)) {
        release_request(owner);
    }
}

void c300x_http_maintenance_close(struct c300x_http_maintenance *owner)
{
    c300x_command_job_close(&owner->job);
    c300x_command_job_init(&owner->job);
    release_request(owner);
}

static int finish_script(struct c300x_http_maintenance *owner)
{
    int client_fd = owner->client_fd;
    char *start = owner->job.output;
    char *end;
    while (*start != '\0' && isspace((unsigned char)*start)) {
        start++;
    }
    end = start + strlen(start);
    while (end > start && isspace((unsigned char)end[-1])) {
        end--;
    }
    *end = '\0';
    if (owner->job.failed) {
        c300x_http_send_json(client_fd, 502, "Bad Gateway", owner->gui_reload
            ? "{\"ok\":false,\"error\":\"reload_failed\"}\n"
            : "{\"ok\":false,\"available\":false,\"state\":\"script_failed\"}\n");
        return 1;
    }
    if (owner->gui_reload) {
        c300x_http_send_json(client_fd, 200, "OK", start[0] == '{' ? start
            : "{\"ok\":true,\"action\":\"reload_gui\"}\n");
        return 1;
    }
    if (start[0] != '{') {
        c300x_http_send_json(client_fd, 502, "Bad Gateway",
            "{\"ok\":false,\"available\":false,\"state\":\"invalid_script_response\"}\n");
        return 1;
    }
    if (owner->records_write) {
        int changed_files = 1;
        (void)c300x_json_int_field(start, "changed_files", &changed_files);
        if (changed_files > 0) {
            owner->record_write(owner->write_context, "qml_patch", owner->action);
        }
    }
    c300x_http_send_json(client_fd, 200, "OK", start);
    return 1;
}

static void start_script(struct c300x_http_maintenance *owner, int client_fd,
    const struct c300x_config *config, const char *action, int records_write,
    int dynamic_homepage, int gui_reload)
{
    const char *program = gui_reload ? config->maintenance_gui_reload_script : config->maintenance_qml_patch_script;
    if (c300x_http_maintenance_busy(owner)) {
        c300x_http_send_json(client_fd, 409, "Conflict", "{\"ok\":false,\"error\":\"maintenance_busy\"}\n");
        return;
    }
    if (access(program, X_OK) != 0) {
        c300x_http_send_json(client_fd, 502, "Bad Gateway", gui_reload
            ? "{\"ok\":false,\"error\":\"reload_script_missing\"}\n"
            : "{\"ok\":false,\"available\":false,\"state\":\"script_missing\"}\n");
        return;
    }
    /* QML writes may need both a failed start and a restored-GUI restart. */
    int timeout_ms = !gui_reload && records_write ? 30000 : 10000;
    if (!c300x_command_job_start(&owner->job, program, action, dynamic_homepage, timeout_ms)) {
        c300x_http_send_json(client_fd, 502, "Bad Gateway", gui_reload
            ? "{\"ok\":false,\"error\":\"reload_failed\"}\n"
            : "{\"ok\":false,\"available\":false,\"state\":\"script_failed\"}\n");
        return;
    }
    owner->client_fd = client_fd;
    owner->gui_reload = gui_reload;
    owner->records_write = records_write;
    snprintf(owner->action, sizeof(owner->action), "%s", action);
    owner->complete = finish_script;
}

int c300x_http_maintenance_route(struct c300x_http_maintenance *owner, int client_fd,
    const struct c300x_config *config, const struct request *request)
{
    static const struct {
        const char *path;
        const char *action;
        const char *confirmation;
    } writes[] = {
        {"/api/v1/maintenance/qml-patch/actions/apply", "apply", "apply_qml_patch"},
        {"/api/v1/maintenance/qml-patch/actions/apply-core", "core-apply", "apply_qml_core_patch"},
        {"/api/v1/maintenance/qml-patch/actions/restore-core", "core-restore", "restore_qml_core_patch"},
        {"/api/v1/maintenance/qml-patch/actions/restore", "restore", "restore_qml_patch"},
        {"/api/v1/maintenance/gui/actions/reload", "reload", "reload_gui"},
    };
    const char *action = NULL, *confirmation = NULL;
    int gui_reload = 0, dynamic_homepage = -1;
    if (strcmp(request->method, "GET") == 0
        && strcmp(request->path, "/api/v1/maintenance/qml-patch") == 0) {
        action = "status";
    } else if (strcmp(request->method, "POST") == 0) {
        for (size_t i = 0; i < sizeof(writes) / sizeof(writes[0]); i++) {
            if (strcmp(request->path, writes[i].path) == 0) {
                action = writes[i].action;
                confirmation = writes[i].confirmation;
                gui_reload = strcmp(action, "reload") == 0;
                break;
            }
        }
    }
    if (action == NULL) {
        return 0;
    }
    if (!maintenance_authorized(config, request)) {
        c300x_http_send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
    } else if (!maintenance_auth_available(config)
        || !(gui_reload ? config->maintenance_gui_reload_enabled : config->maintenance_qml_patch_enabled)) {
        c300x_http_send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
    } else if (confirmation != NULL && !confirm_matches(request, confirmation)) {
        c300x_http_send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
    } else {
        if (strcmp(action, "apply") == 0) {
            (void)c300x_json_bool_field(request->body, "dynamic_homepage", &dynamic_homepage);
            (void)c300x_json_bool_field(request->body, "dynamicHomepage", &dynamic_homepage);
        }
        start_script(owner, client_fd, config, action, confirmation != NULL && !gui_reload,
            dynamic_homepage, gui_reload);
    }
    return 1;
}
