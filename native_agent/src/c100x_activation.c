#include "c100x_activation.h"
#include "c100x_boot_check.h"
#include "c100x_payload.h"
#include "device_detect.h"
#include "json_util.h"

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* The display's lease must hold this long in the trial boot before a check. */
#ifndef C100X_ACTIVATION_SETTLE_MS
#define C100X_ACTIVATION_SETTLE_MS 15000
#endif
/* ... and appear within this time after the agent started. */
#ifndef C100X_ACTIVATION_GUI_WAIT_MS
#define C100X_ACTIVATION_GUI_WAIT_MS 600000
#endif
#ifndef C100X_ACTIVATION_CONFIRM_RETRY_MS
#define C100X_ACTIVATION_CONFIRM_RETRY_MS 60000
#endif
#define CONFIRM_ATTEMPTS 3
/* A lease renewal or the probe's hand-over is not a lost display. */
#define LEASE_GAP_MS 5000
/* A station still up this long after a reboot request gets one more. */
#ifndef C100X_ACTIVATION_REBOOT_RETRY_MS
#define C100X_ACTIVATION_REBOOT_RETRY_MS 600000
#endif

enum reboot_reason { REBOOT_NONE = 0, REBOOT_PREPARED, REBOOT_TRIAL_FAILED, REBOOT_RESTORED };

static const char *const action_names[] = {"", "status", "prepare", "restore", "recover", "boot-confirm"};
static const int action_timeouts_ms[] = {0, 30000, 120000, 120000, 120000, 60000};
static const char *const phase_names[] = {"unknown", "stock", "installed", "prepared", "trial", "stale"};

void c100x_activation_init(struct c100x_activation *activation, const char *bundle)
{
    memset(activation, 0, sizeof(*activation));
    c300x_command_job_init(&activation->job);
    activation->blocked = activation->boot_check = "";
    struct c300x_device_profile profile = c300x_device_profile();
    /* Only on a station that names itself a C100X and runs its display program. */
    if (profile.model != C300X_DEVICE_MODEL_C100X || profile.model_check == C300X_MODEL_CHECK_MISMATCH
        || bundle == NULL
        || strlen(bundle) >= sizeof(activation->bundle)) {
        return;
    }
    snprintf(activation->bundle, sizeof(activation->bundle), "%s", bundle);
    activation->enabled = 1;
    activation->refresh = 1;
    activation->boot_check = c100x_boot_check();
}

int c100x_activation_busy(const struct c100x_activation *activation)
{
    return activation->job.pid > 0 || activation->queued != C100X_ACTION_NONE;
}

int c100x_activation_writing(const struct c100x_activation *activation)
{
    return (activation->job.pid > 0 && activation->running != C100X_ACTION_STATUS)
        || activation->queued != C100X_ACTION_NONE;
}

int c100x_activation_confirmed(const struct c100x_activation *activation)
{
    return activation->enabled && activation->known && activation->confirmed && !*activation->boot_check;
}

int c100x_activation_prepare(const struct c100x_activation *activation, struct pollfd *fd)
{
    int timeout = c300x_command_job_prepare(&activation->job, fd);
    /* Waiting for the display, a check or the idle time: look again each second. */
    if (activation->enabled && timeout < 0 && (activation->refresh || activation->queued
            || activation->phase == C100X_PHASE_TRIAL || activation->reboot_reason != REBOOT_NONE)) {
        return 1000;
    }
    return timeout;
}

static void set_error(struct c100x_activation *activation, enum c100x_display_action action, const char *text)
{
    size_t used = 0;
    activation->error_from_status = action == C100X_ACTION_STATUS;
    /* The script's own message, reduced to plain characters for the JSON. */
    for (; *text != '\0' && *text != '\n' && used + 1 < sizeof(activation->error); text++) {
        char c = *text;
        activation->error[used++] = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == ' '
            || c == '_' || c == '-' || c == ';' || c == ':' ? c : '_';
    }
    activation->error[used] = '\0';
}

static int start(struct c100x_activation *activation, enum c100x_display_action action)
{
    char *argv[] = {"/bin/sh", "-c", "exec /bin/sh \"$0\" \"$1\" 2>&1", activation->bundle,
        (char *)action_names[action], NULL};
    if (!c100x_payload_usable(activation->bundle)) {
        set_error(activation, action, "payload unavailable");
        if (action == C100X_ACTION_STATUS) {
            activation->known = 0;
        }
        return 0;
    }
    if (!c300x_command_job_start_output(&activation->job, argv[0], argv, action_timeouts_ms[action])) {
        set_error(activation, action, "job start failed");
        return 0;
    }
    activation->running = action;
    return 1;
}

static enum c100x_display_phase phase_of(const char *name)
{
    for (size_t index = 1; index < sizeof(phase_names) / sizeof(phase_names[0]); index++) {
        if (strcmp(name, phase_names[index]) == 0) {
            return (enum c100x_display_phase)index;
        }
    }
    return C100X_PHASE_UNKNOWN;
}

static int hex_or_empty(const char *value)
{
    size_t length = strlen(value);
    return (length == 0 || length == 64) && strspn(value, "0123456789abcdef") == length;
}

static int read_status(struct c100x_activation *activation, const char *line)
{
    char phase[16], generation[65], available[65], result[16];
    int ok = 0, switched = 0, confirmed = 0, reboot_due = 0;

    if (!c300x_json_object_valid(line) || !c300x_json_bool_field(line, "ok", &ok) || !ok
        || !c300x_json_bool_field(line, "trial_switched", &switched)
        || !c300x_json_bool_field(line, "confirmed", &confirmed)
        || !c300x_json_bool_field(line, "reboot_due", &reboot_due)
        || c300x_json_string_field_checked(line, "phase", phase, sizeof(phase)) != 1
        || c300x_json_string_field_checked(line, "generation", generation, sizeof(generation)) != 1
        || c300x_json_string_field_checked(line, "available", available, sizeof(available)) != 1
        || c300x_json_string_field_checked(line, "last_result", result, sizeof(result)) != 1
        || phase_of(phase) == C100X_PHASE_UNKNOWN || !hex_or_empty(generation) || !hex_or_empty(available)
        || strspn(result, "abcdefghijklmnopqrstuvwxyz_") != strlen(result)) {
        return 0;
    }
    activation->phase = phase_of(phase);
    activation->switched = switched;
    activation->confirmed = confirmed;
    activation->reboot_due = reboot_due;
    snprintf(activation->generation, sizeof(activation->generation), "%s", generation);
    snprintf(activation->available, sizeof(activation->available), "%s", available);
    snprintf(activation->result, sizeof(activation->result), "%s", result);
    return 1;
}

static void job_done(struct c100x_activation *activation)
{
    char *output = activation->job.output;
    char *line = output, *last_json = NULL, *last_text = NULL;
    int ok = !activation->job.failed && activation->job.exit_status == 0;
    enum c100x_display_action action = activation->running;

    /* The last JSON line is the result; any other last line is the error. */
    for (char *next; line != NULL && *line != '\0'; line = next) {
        next = strchr(line, '\n');
        if (next != NULL) {
            *next++ = '\0';
        }
        if (*line == '{') {
            last_json = line;
        } else if (*line != '\0') {
            last_text = line;
        }
    }
    if (action == C100X_ACTION_STATUS) {
        activation->known = ok && last_json != NULL && read_status(activation, last_json);
    } else {
        activation->refresh = 1;
    }
    if (ok && last_json != NULL && (action != C100X_ACTION_STATUS || activation->known)) {
        /* A status read keeps the error of the action before it. */
        if (action != C100X_ACTION_STATUS || activation->error_from_status) {
            activation->error[0] = '\0';
        }
    } else {
        set_error(activation, action, last_text != NULL ? last_text + (strncmp(last_text, "c100x_display: ", 15) ? 0 : 15)
            : ok ? "invalid status" : activation->job.exit_status < 0 ? "timed out" : "failed");
    }
    c300x_command_job_close(&activation->job);
    c300x_command_job_init(&activation->job);
    activation->running = C100X_ACTION_NONE;
    activation->boot_check = c100x_boot_check();
}

static void run_jobs(struct c100x_activation *activation)
{
    if (activation->job.pid != 0) {
        c300x_command_job_tick(&activation->job);
        if (!activation->job.complete || activation->job.pid != 0) {
            return;
        }
        job_done(activation);
    }
    if (activation->queued != C100X_ACTION_NONE) {
        enum c100x_display_action action = activation->queued;
        activation->queued = C100X_ACTION_NONE;
        if (!start(activation, action)) {
            activation->refresh = 1;
        }
    } else if (activation->refresh) {
        activation->refresh = 0;
        (void)start(activation, C100X_ACTION_STATUS);
    }
}

/* The trial boot: wait for the trial display's lease, let it settle, check it. */
static void trial_step(struct c100x_activation *activation, const struct c100x_activation_inputs *inputs)
{
    long long now = inputs->now_ms;
    int alive = inputs->lease && inputs->lease_generation != NULL
        && strcmp(inputs->lease_generation, activation->generation) == 0;

    if (alive) {
        activation->lease_since_ms = activation->lease_since_ms ? activation->lease_since_ms : now;
        activation->lease_lost_ms = 0;
    } else if (activation->lease_since_ms) {
        activation->lease_lost_ms = activation->lease_lost_ms ? activation->lease_lost_ms : now;
        if (now - activation->lease_lost_ms > LEASE_GAP_MS) {
            activation->lease_since_ms = 0;
        }
    }
    if (!activation->lease_since_ms) {
        activation->trial_failed = now - activation->started_ms >= C100X_ACTIVATION_GUI_WAIT_MS;
        return;
    }
    if (!alive || inputs->lease_blocked || now - activation->lease_since_ms < C100X_ACTIVATION_SETTLE_MS
        || now < activation->next_confirm_ms) {
        return;
    }
    if (activation->attempts >= CONFIRM_ATTEMPTS) {
        activation->trial_failed = 1;
        return;
    }
    activation->attempts++;
    activation->next_confirm_ms = now + C100X_ACTIVATION_CONFIRM_RETRY_MS;
    activation->queued = C100X_ACTION_BOOT_CONFIRM;
}

static int reboot_step(struct c100x_activation *activation, const struct c100x_activation_inputs *inputs)
{
    long long now = inputs->now_ms;
    enum reboot_reason reason = !activation->known ? REBOOT_NONE
        : *activation->boot_check ? (activation->reboot_due ? REBOOT_RESTORED : REBOOT_NONE)
        : activation->phase == C100X_PHASE_PREPARED && activation->switched ? REBOOT_PREPARED
        : activation->phase == C100X_PHASE_TRIAL && activation->trial_failed ? REBOOT_TRIAL_FAILED
        : activation->reboot_due ? REBOOT_RESTORED : REBOOT_NONE;
    const char *blocked;

    /* At most one request per reason; a second one only if the station is still up much later. */
    if ((int)reason != activation->reboot_reason) {
        activation->reboot_reason = (int)reason;
        activation->reboot_requests = 0;
        activation->idle_since_ms = 0;
    }
    activation->blocked = "";
    if (reason == REBOOT_NONE) {
        return 0;
    }
    if (activation->reboot_requests > 0 && now - activation->reboot_ms < C100X_ACTIVATION_REBOOT_RETRY_MS) {
        activation->blocked = "reboot_requested";
        return 0;
    }
    if (activation->reboot_requests >= 2) {
        activation->blocked = "reboot_failed";
        return 0;
    }
    if ((blocked = c100x_reboot_gate(activation, inputs)) != NULL) {
        activation->blocked = blocked;
        activation->idle_since_ms = 0;
        return 0;
    }
    activation->idle_since_ms = activation->idle_since_ms ? activation->idle_since_ms : now;
    if (now - activation->idle_since_ms < C100X_ACTIVATION_IDLE_MS) {
        activation->blocked = "waiting_for_idle";
        return 0;
    }
    activation->reboot_requests++;
    activation->reboot_ms = now;
    activation->idle_since_ms = 0;
    activation->blocked = "reboot_requested";
    return 1;
}

int c100x_activation_tick(struct c100x_activation *activation, const struct c100x_activation_inputs *inputs)
{
    if (!activation->enabled) {
        return 0;
    }
    activation->started_ms = activation->started_ms ? activation->started_ms : inputs->now_ms;
    run_jobs(activation);
    if (activation->job.pid == 0 && activation->queued == C100X_ACTION_NONE && !activation->refresh
        && activation->known && !*activation->boot_check) {
        int pending = activation->phase == C100X_PHASE_PREPARED || activation->phase == C100X_PHASE_TRIAL;
        if (pending && !activation->switched && !activation->recovered) {
            /* A prepare that never switched: the running display never saw it. */
            activation->recovered = 1;
            activation->queued = C100X_ACTION_RECOVER;
        } else if (activation->phase == C100X_PHASE_TRIAL && activation->switched && !activation->trial_failed) {
            trial_step(activation, inputs);
        }
        run_jobs(activation);
    }
    /* The display functions follow the confirmed adapter, also when it is restored. */
    c300x_device_set_display_adapter_confirmed(c100x_activation_confirmed(activation));
    return reboot_step(activation, inputs);
}

void c100x_activation_close(struct c100x_activation *activation)
{
    if (activation->job.pid > 0) {
        (void)kill(-activation->job.pid, SIGTERM);
        for (int round = 0; round < 150 && activation->job.pid > 0; round++) {
            c300x_command_job_tick(&activation->job);
            if (activation->job.pid > 0) {
                (void)usleep(10000);
            }
        }
    }
    c300x_command_job_close(&activation->job);
    c300x_command_job_init(&activation->job);
}

const char *c100x_activation_request(struct c100x_activation *activation, enum c100x_display_action action)
{
    if (!activation->enabled) {
        return "c100x_required";
    }
    if (action == C100X_ACTION_STATUS) {
        /* Only an unknown status is read again; a known one changes only by the jobs. */
        if (!activation->known && !c100x_activation_busy(activation)) {
            activation->refresh = 1;
        }
        return NULL;
    }
    if (c100x_activation_busy(activation) || activation->refresh) {
        return "c100x_display_busy";
    }
    if (!activation->known) {
        return "c100x_display_status_unknown";
    }
    if (*activation->boot_check && action == C100X_ACTION_PREPARE) {
        return "c100x_display_boot_check_failed";
    }
    if (activation->phase == C100X_PHASE_PREPARED || activation->phase == C100X_PHASE_TRIAL
        || activation->phase == C100X_PHASE_STALE) {
        if (action == C100X_ACTION_PREPARE) {
            return "c100x_display_trial_pending";
        }
    }
    activation->queued = action;
    activation->attempts = 0;
    activation->trial_failed = 0;
    activation->recovered = 0;
    activation->error[0] = '\0';
    return NULL;
}

int c100x_activation_json(const struct c100x_activation *activation, char *out, size_t out_len)
{
    int idle = activation->known && !c100x_activation_busy(activation) && !activation->refresh;
    int pending = activation->phase == C100X_PHASE_PREPARED || activation->phase == C100X_PHASE_TRIAL
        || activation->phase == C100X_PHASE_STALE;
    /* The installed pages are this payload's and confirmed: nothing to activate. */
    int current = activation->confirmed && (activation->available[0] == '\0'
        || strcmp(activation->available, activation->generation) == 0);
    int written = snprintf(out, out_len,
        "{\"supported\":true,\"status_known\":%s,\"busy\":%s,\"phase\":\"%s\",\"trial_switched\":%s,"
        "\"confirmed\":%s,\"generation\":\"%s\",\"available\":\"%s\",\"last_result\":\"%s\","
        "\"last_error\":\"%s\",\"reboot_pending\":%s,\"reboot_blocked\":\"%s\","
        "\"activate\":%s,\"restore\":%s,\"alert_sound\":false,\"boot_check\":\"%s\"}",
        activation->known ? "true" : "false",
        c100x_activation_busy(activation) ? "true" : "false",
        phase_names[activation->known ? activation->phase : C100X_PHASE_UNKNOWN],
        activation->known && activation->switched ? "true" : "false",
        c100x_activation_confirmed(activation) ? "true" : "false",
        activation->known ? activation->generation : "",
        activation->known ? activation->available : "",
        activation->known ? activation->result : "",
        activation->error,
        activation->reboot_reason != REBOOT_NONE ? "true" : "false",
        activation->blocked,
        idle && !pending && !current && !*activation->boot_check ? "true" : "false",
        idle && activation->phase != C100X_PHASE_STOCK ? "true" : "false", activation->boot_check);
    return written >= 0 && (size_t)written < out_len;
}
