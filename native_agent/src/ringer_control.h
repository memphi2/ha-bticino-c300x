#ifndef C300X_RINGER_CONTROL_H
#define C300X_RINGER_CONTROL_H

#include <poll.h>

#define C300X_RINGER_CONTROL_POLL_FDS 2
#define C300X_RINGER_CONTROL_TIMEOUT_MS 5000

struct c300x_ringer_command {
    int muted;
    int has_volume;
    int volume;
};

/* Return zero while device readback still needs confirmation. */
typedef int (*c300x_ringer_apply_fn)(int fd, const struct c300x_ringer_command *command, void *ctx);

struct c300x_ringer_control {
    int gui_fd;
    int client_fd;
    long long deadline_ms;
    int gui_confirmed;
    int device_confirmed;
    int event_verified;
    c300x_ringer_apply_fn apply;
    void *apply_ctx;
    char id[33];
    struct c300x_ringer_command command;
    /* The GUI's own mute flag as last seen: -1 unknown. */
    int gui_muted;
    int sync_wanted;
    char sync_id[33];
    long long sync_deadline_ms;
};

void c300x_ringer_control_init(struct c300x_ringer_control *control);
/* Parse a GUI query after caller authorization; zero retains the connection. */
int c300x_ringer_control_next(
    struct c300x_ringer_control *control, int fd, const char *query,
    c300x_ringer_apply_fn apply, void *ctx
);
void c300x_ringer_control_request(
    struct c300x_ringer_control *control, int fd, const struct c300x_ringer_command *command
);
int c300x_ringer_control_timeout_ms(const struct c300x_ringer_control *control);
void c300x_ringer_control_expire(struct c300x_ringer_control *control);
/* Return nonzero when a pending command consumed the state event. */
int c300x_ringer_control_confirm(
    struct c300x_ringer_control *control, int muted
);
/* A device mute state no command asked for. The vendor GUI follows a mute on
 * the bus but never an unmute; with sync set, an unmute is pushed to it. */
void c300x_ringer_control_observe(struct c300x_ringer_control *control, int muted, int sync);
int c300x_ringer_control_pollfds(const struct c300x_ringer_control *control, struct pollfd *fds);
void c300x_ringer_control_handle_pollfds(struct c300x_ringer_control *control, const struct pollfd *fds, int count);
void c300x_ringer_control_close(struct c300x_ringer_control *control);

#endif
