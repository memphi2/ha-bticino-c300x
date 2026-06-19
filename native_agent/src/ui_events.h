#ifndef C300X_UI_EVENTS_H
#define C300X_UI_EVENTS_H

#include <poll.h>
#include <stddef.h>
#include <time.h>

#define C300X_UI_EVENT_MAX_WAITERS 4
#define C300X_UI_EVENT_WAIT_SECONDS 60

struct c300x_ui_event_waiter {
    int fd;
    unsigned long since;
    time_t deadline;
};

struct c300x_ui_events {
    unsigned long revision;
    struct c300x_ui_event_waiter waiters[C300X_UI_EVENT_MAX_WAITERS];
    unsigned long waiter_overflows;
    char topic[64];
};

typedef void (*c300x_ui_event_send_json_fn)(
    int client_fd,
    int status,
    const char *reason,
    const char *body,
    void *ctx
);

void c300x_ui_events_init(struct c300x_ui_events *events);
int c300x_ui_events_waiter_count(const struct c300x_ui_events *events);
int c300x_ui_events_timeout_ms(const struct c300x_ui_events *events, time_t now);
void c300x_ui_events_notify(
    struct c300x_ui_events *events,
    const char *topic,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
);
void c300x_ui_events_expire_waiters(
    struct c300x_ui_events *events,
    time_t now,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
);
void c300x_ui_events_close_all(
    struct c300x_ui_events *events,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
);
int c300x_ui_events_store_waiter(
    struct c300x_ui_events *events,
    int client_fd,
    unsigned long since,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx,
    int *overflowed
);
int c300x_ui_events_pollfds(
    const struct c300x_ui_events *events,
    struct pollfd *poll_fds,
    int *poll_slots,
    int max_fds
);
void c300x_ui_events_handle_pollfds(
    struct c300x_ui_events *events,
    const struct pollfd *poll_fds,
    const int *poll_slots,
    int poll_count,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
);
void c300x_ui_events_status_json(
    const struct c300x_ui_events *events,
    char *out,
    size_t out_len
);
void c300x_ui_events_send_changed(
    const struct c300x_ui_events *events,
    int client_fd,
    int changed,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
);

#endif
