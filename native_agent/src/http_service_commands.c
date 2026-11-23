#include "http_service_commands.h"
#include "http_service_dispatch.h"
#include "http_util.h"
#include "json_util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef C300X_SSH_INIT_SCRIPT
#define C300X_SSH_INIT_SCRIPT "/etc/init.d/dropbear"
#endif
#ifndef C300X_SSH_STATUS_COMMAND
#define C300X_SSH_STATUS_COMMAND "pidof dropbear >/dev/null 2>&1"
#endif
/* A hanging init script or status check must not hold the maintenance
 * slot, and with it every other maintenance request, for good. */
#ifndef C300X_SSH_COMMAND_TIMEOUT_MS
#define C300X_SSH_COMMAND_TIMEOUT_MS 60000
#endif
#ifndef C300X_SSH_STATUS_TIMEOUT_MS
#define C300X_SSH_STATUS_TIMEOUT_MS 15000
#endif
#ifndef C300X_REBOOT_PROGRAM
#define C300X_REBOOT_PROGRAM "/sbin/reboot"
#endif

enum service_action { SSH_STATUS, SSH_START, SSH_STOP, SSH_SET, REBOOT, REMOVE };
enum service_phase { SERVICE_COMMAND, STATUS_COMMAND, START_SSH };
struct service_request {
    const struct c300x_config *config;
    c300x_schedule_command_fn schedule;
    enum service_action action;
    enum service_phase phase;
    int display;
    int requested_ssh;
    c300x_reboot_reply_fn reply;
    void *reply_context;
    void (*destroy_reply)(void *);
};

static void destroy_service(void *context)
{
    struct service_request *state = context;
    if (state->destroy_reply != NULL) {
        state->destroy_reply(state->reply_context);
    }
    free(state);
}

static void command_failed(int fd)
{
    c300x_http_send_json(fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"maintenance_command_failed\"}\n");
}

static void ssh_status(int fd, int running)
{
    char body[96];
    snprintf(body, sizeof(body), "{\"ok\":true,\"enabled\":%s,\"running\":%s}\n",
        running ? "true" : "false", running ? "true" : "false");
    c300x_http_send_json(fd, 200, "OK", body);
}

static void probe_failed(int fd, const struct service_request *state)
{
    if (state->display) {
        command_failed(fd);
    } else {
        ssh_status(fd, 0);
    }
}

static int start_command(struct c300x_http_maintenance *owner, const char *program, const char *action)
{
    char *argv[] = {(char *)program, (char *)action, NULL};
    return c300x_command_job_start_wait(&owner->job, program, argv, C300X_SSH_COMMAND_TIMEOUT_MS);
}

static int start_status(struct c300x_http_maintenance *owner, struct service_request *state)
{
    char *argv[] = {"/bin/sh", "-c", C300X_SSH_STATUS_COMMAND, NULL};
    state->phase = STATUS_COMMAND;
    return c300x_command_job_start_wait(&owner->job, argv[0], argv, C300X_SSH_STATUS_TIMEOUT_MS);
}

static void accepted(int fd, enum service_action action)
{
    c300x_http_send_json(fd, 202, "Accepted", action == REMOVE
        ? "{\"ok\":true,\"action\":\"remove_agent\",\"scheduled\":true,\"ssh_kept_running\":true}\n"
        : "{\"ok\":true,\"action\":\"reboot\",\"scheduled\":true}\n");
}

static void reply_action(int fd, struct service_request *state, int ok)
{
    if (state->reply != NULL) {
        state->reply(fd, ok, state->reply_context);
    } else if (ok) {
        accepted(fd, state->action);
    } else {
        command_failed(fd);
    }
}

static void schedule_action(int fd, struct service_request *state)
{
    const struct c300x_config *config = state->config;
    /* The configuration only takes a positive delay, so a reboot is always scheduled. */
    int ok = state->action == REMOVE
        ? state->schedule(config->maintenance_agent_remove_script, "remove", 500)
        : state->schedule(C300X_REBOOT_PROGRAM, NULL, config->maintenance_reboot_delay_ms);
    reply_action(fd, state, ok);
}

static int begin_shutdown(struct c300x_http_maintenance *owner, int fd,
    struct service_request *state)
{
    state->phase = START_SSH;
    if (state->config->maintenance_ssh_start_enabled
        && start_command(owner, C300X_SSH_INIT_SCRIPT, "start")) {
        return 1;
    }
    schedule_action(fd, state);
    return 0;
}

static int finish_service(struct c300x_http_maintenance *owner)
{
    struct service_request *state = owner->context;
    int fd = owner->client_fd;
    if (state->phase == START_SSH) {
        /* The old reboot/remove paths deliberately ignore SSH start failure. */
        schedule_action(fd, state);
        return 1;
    }
    if (state->phase == STATUS_COMMAND) {
        int running = !owner->job.failed;
        /* pidof returns 1 for no daemon. A timeout or failed probe is unknown,
         * not proof that a requested stop succeeded. */
        if (state->display && ((owner->job.failed && owner->job.exit_status != 1)
            || (state->action == SSH_SET && state->requested_ssh != running))) {
            command_failed(fd);
        } else {
            ssh_status(fd, running);
        }
    } else if (owner->job.failed) {
        command_failed(fd);
    } else if (state->action == SSH_SET) {
        if (start_status(owner, state)) {
            return 0;
        }
        probe_failed(fd, state);
    } else {
        c300x_http_send_json(fd, 200, "OK", state->action == SSH_START
            ? "{\"ok\":true,\"action\":\"ssh_start\",\"enabled\":true,\"running\":true}\n"
            : "{\"ok\":true,\"action\":\"ssh_stop\",\"enabled\":false,\"running\":false}\n");
    }
    return 1;
}
static void hold_service(struct c300x_http_maintenance *owner, int fd, struct service_request *state)
{
    owner->client_fd = fd;
    owner->context = state;
    owner->destroy_context = destroy_service;
    owner->complete = finish_service;
}

void c300x_http_service_reboot(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, c300x_schedule_command_fn schedule,
    c300x_reboot_reply_fn reply, void *context, void (*destroy)(void *))
{
    struct service_request *state = calloc(1, sizeof(*state));
    if (state == NULL) {
        reply(fd, 0, context);
        destroy(context);
        return;
    }
    state->config = config;
    state->schedule = schedule;
    state->action = REBOOT;
    state->reply = reply;
    state->reply_context = context;
    state->destroy_reply = destroy;
    if (begin_shutdown(owner, fd, state)) {
        hold_service(owner, fd, state);
    } else {
        destroy_service(state);
    }
}

int c300x_service_dispatch(int display, struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, const struct request *request,
    c300x_schedule_command_fn schedule)
{
    enum service_action action;
    const char *confirmation = NULL;
    int enabled = 0, supported;
    if (strcmp(request->method, "GET") == 0
        && strcmp(request->path, "/api/v1/maintenance/ssh") == 0) {
        action = SSH_STATUS;
    } else if (strcmp(request->method, "POST") != 0) {
        return 0;
    } else if (strcmp(request->path, "/api/v1/maintenance/ssh") == 0) {
        action = SSH_SET;
    } else if (strcmp(request->path, "/api/v1/maintenance/ssh/actions/start") == 0) {
        action = SSH_START;
        confirmation = "start_ssh";
    } else if (strcmp(request->path, "/api/v1/maintenance/ssh/actions/stop") == 0) {
        action = SSH_STOP;
        confirmation = "stop_ssh";
    } else if (strcmp(request->path, "/api/v1/maintenance/reboot") == 0) {
        action = REBOOT;
        confirmation = "reboot";
    } else if (strcmp(request->path, "/api/v1/maintenance/agent/actions/remove") == 0) {
        action = REMOVE;
        confirmation = "remove_agent";
    } else {
        return 0;
    }
    supported = action == REBOOT ? config->maintenance_reboot_enabled
        : action == REMOVE ? config->maintenance_agent_remove_enabled : config->maintenance_ssh_start_enabled;
    if (!(display ? config->maintenance_enabled : maintenance_authorized(config, request))) {
        c300x_http_send_json(fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return 1;
    }
    if (!supported) {
        c300x_http_send_json(fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return 1;
    }
    if (confirmation != NULL && !confirm_matches(request, confirmation)) {
        c300x_http_send_json(fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return 1;
    }
    if (action == SSH_SET && !c300x_json_bool_field(request->body, "enabled", &enabled)) {
        c300x_http_send_json(fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_ssh_enabled_required\"}\n");
        return 1;
    }
    struct service_request *state = calloc(1, sizeof(*state));
    if (state == NULL) {
        c300x_http_send_json(fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        return 1;
    }
    state->config = config;
    state->schedule = schedule;
    state->action = action;
    state->display = display;
    state->requested_ssh = enabled;
    int pending;
    if (action == SSH_STATUS) {
        pending = start_status(owner, state);
        if (!pending) {
            probe_failed(fd, state);
        }
    } else if (display && action == REBOOT) {
        schedule_action(fd, state);
        pending = 0;
    } else if (action == REBOOT || action == REMOVE) {
        pending = begin_shutdown(owner, fd, state);
    } else {
        state->phase = SERVICE_COMMAND;
        pending = start_command(owner, C300X_SSH_INIT_SCRIPT,
            action == SSH_START || (action == SSH_SET && enabled) ? "start" : "stop");
        if (!pending) {
            command_failed(fd);
        }
    }
    if (pending) {
        hold_service(owner, fd, state);
    } else {
        destroy_service(state);
    }
    return 1;
}
