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

struct c300x_ringer_control {
    int gui_fd;
    int client_fd;
    long long deadline_ms;
    int gui_confirmed;
    char id[33];
    struct c300x_ringer_command command;
};

/* Return zero while device readback still needs confirmation. */
typedef int (*c300x_ringer_apply_fn)(int fd, const struct c300x_ringer_command *command, void *ctx);

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
    struct c300x_ringer_control *control, int muted,
    c300x_ringer_apply_fn apply, void *ctx
);
int c300x_ringer_control_pollfds(const struct c300x_ringer_control *control, struct pollfd *fds);
void c300x_ringer_control_handle_pollfds(struct c300x_ringer_control *control, const struct pollfd *fds, int count);
void c300x_ringer_control_close(struct c300x_ringer_control *control);

#endif
