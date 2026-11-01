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
    char id[33];
    struct c300x_ringer_command command;
};

typedef void (*c300x_ringer_apply_fn)(int fd, const struct c300x_ringer_command *command, void *ctx);

void c300x_ringer_control_init(struct c300x_ringer_control *control);
/* Return zero when the connection is retained by the control channel. */
int c300x_ringer_control_next(
    struct c300x_ringer_control *control, int fd, const char *completed, int muted,
    c300x_ringer_apply_fn apply, void *ctx
);
void c300x_ringer_control_request(
    struct c300x_ringer_control *control, int fd, const struct c300x_ringer_command *command
);
int c300x_ringer_control_timeout_ms(const struct c300x_ringer_control *control);
void c300x_ringer_control_expire(struct c300x_ringer_control *control);
int c300x_ringer_control_pollfds(const struct c300x_ringer_control *control, struct pollfd *fds);
void c300x_ringer_control_handle_pollfds(struct c300x_ringer_control *control, const struct pollfd *fds, int count);
void c300x_ringer_control_close(struct c300x_ringer_control *control);

#endif
