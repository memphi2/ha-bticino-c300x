#ifndef C100X_ACTIVATION_H
#define C100X_ACTIVATION_H

#include "command_job.h"

#include <poll.h>

#define C100X_ACTIVATION_POLL_FDS 1

enum c100x_display_action {
    C100X_ACTION_NONE = 0,
    C100X_ACTION_STATUS,
    C100X_ACTION_PREPARE,
    C100X_ACTION_RESTORE,
    C100X_ACTION_RECOVER,
    C100X_ACTION_BOOT_CONFIRM,
};

enum c100x_display_phase {
    C100X_PHASE_UNKNOWN = 0,
    C100X_PHASE_STOCK,
    C100X_PHASE_INSTALLED,
    C100X_PHASE_PREPARED,
    C100X_PHASE_TRIAL,
    C100X_PHASE_STALE,
};

/* What the agent sees around the station, gathered for every loop step. */
struct c100x_activation_inputs {
    long long now_ms;        /* monotonic, so also the time since the station booted */
    int door_events;         /* door entry frames are heard: calls can be seen */
    int station_busy;        /* a media session, an announcement or a maintenance job */
    int lease;               /* the display holds its presence lease */
    int lease_blocked;       /* ... and reports a call or another vendor state */
    const char *lease_generation;
    int reboot_allowed;      /* maintenance with reboot enabled */
};

/* The C100X display pages become live only with a reboot: the display
 * program cannot be restarted. The transaction script decides on disk; this
 * state machine runs it as a job, confirms the trial boot, and asks for the
 * reboot only while the station is idle. Inert on a C300X. */
struct c100x_activation {
    int enabled;
    char bundle[512];
    struct c300x_command_job job;
    enum c100x_display_action running;
    enum c100x_display_action queued;
    int refresh;
    /* The last status the script reported; known only after one succeeded. */
    int known;
    enum c100x_display_phase phase;
    int switched;
    int confirmed;
    int reboot_due;
    char generation[65];
    char available[65];
    char result[16];
    char error[96];
    int error_from_status;
    /* The trial boot: the display's lease, its settling and the checks. */
    long long started_ms;
    long long lease_since_ms;
    long long lease_lost_ms;
    long long next_confirm_ms;
    int attempts;
    int trial_failed;
    int recovered;
    /* The reboot: calls seen on the bus and the idle time before it. */
    long long call_frame_ms;
    long long call_open_ms;
    long long idle_since_ms;
    long long reboot_ms;
    int reboot_reason;
    int reboot_requests;
    const char *blocked;
};

void c100x_activation_init(struct c100x_activation *activation, const char *bundle);
int c100x_activation_prepare(const struct c100x_activation *activation, struct pollfd *fd);
/* One loop step. 1: the station is idle and the reboot is due now. */
int c100x_activation_tick(struct c100x_activation *activation, const struct c100x_activation_inputs *inputs);
/* TERM first, so the script's own trap cleans up; KILL after 1.5 s. */
void c100x_activation_close(struct c100x_activation *activation);
int c100x_activation_busy(const struct c100x_activation *activation);
/* A job that changes the display files runs or waits: other maintenance writes wait. */
int c100x_activation_writing(const struct c100x_activation *activation);
int c100x_activation_confirmed(const struct c100x_activation *activation);
void c100x_activation_door_frame(struct c100x_activation *activation, const char *frame, long long now_ms);
/* NULL once queued, else why not. */
const char *c100x_activation_request(struct c100x_activation *activation, enum c100x_display_action action);
/* The c100x_display object of the capabilities and the status route. */
int c100x_activation_json(const struct c100x_activation *activation, char *out, size_t out_len);

#endif
