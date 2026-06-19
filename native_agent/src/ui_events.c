#include "ui_events.h"

#include "http_util.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

static int timeout_until_ms(time_t now, time_t due)
{
    if (due <= now) {
        return 0;
    }
    if (due - now > 3600) {
        return 3600 * 1000;
    }
    return (int)((due - now) * 1000);
}

static int min_timeout_ms(int current, int candidate)
{
    if (candidate < 0) {
        return current;
    }
    if (current < 0 || candidate < current) {
        return candidate;
    }
    return current;
}

static size_t json_escape_string(const char *value, char *out, size_t out_len)
{
    size_t used = 0;

    if (out_len == 0) {
        return 0;
    }
    for (size_t index = 0; value[index] != '\0' && used + 1 < out_len; index++) {
        unsigned char ch = (unsigned char)value[index];
        if (ch == '\\' || ch == '"') {
            if (used + 2 >= out_len) {
                break;
            }
            out[used++] = '\\';
            out[used++] = (char)ch;
            continue;
        }
        if (ch < 0x20) {
            if (used + 6 >= out_len) {
                break;
            }
            used += (size_t)snprintf(out + used, out_len - used, "\\u%04x", ch);
            continue;
        }
        out[used++] = (char)ch;
    }
    out[used] = '\0';
    return used;
}

static void ui_event_send(
    const struct c300x_ui_events *events,
    int client_fd,
    int changed,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
)
{
    char body[1024];
    char escaped_topic[96];
    char quoted_topic[100];
    const char *topic_json = "null";

    if (events->topic[0] != '\0') {
        json_escape_string(events->topic, escaped_topic, sizeof(escaped_topic));
        snprintf(quoted_topic, sizeof(quoted_topic), "\"%s\"", escaped_topic);
        topic_json = quoted_topic;
    }
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"changed\":%s,\"revision\":%lu,\"topic\":%s}\n",
        changed ? "true" : "false",
        events->revision,
        topic_json
    );
    send_json_fn(client_fd, 200, "OK", body, ctx);
}

static void close_waiter(
    struct c300x_ui_events *events,
    size_t index,
    int changed,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
)
{
    struct c300x_ui_event_waiter *waiter;
    int fd;

    if (index >= C300X_UI_EVENT_MAX_WAITERS) {
        return;
    }
    waiter = &events->waiters[index];
    fd = waiter->fd;
    if (fd < 0) {
        return;
    }
    waiter->fd = -1;
    waiter->since = 0;
    waiter->deadline = 0;
    ui_event_send(events, fd, changed, send_json_fn, ctx);
    close_agent_socket(fd);
}

void c300x_ui_events_init(struct c300x_ui_events *events)
{
    size_t index;

    memset(events, 0, sizeof(*events));
    for (index = 0; index < C300X_UI_EVENT_MAX_WAITERS; index++) {
        events->waiters[index].fd = -1;
    }
}

int c300x_ui_events_waiter_count(const struct c300x_ui_events *events)
{
    int count = 0;
    size_t index;

    for (index = 0; index < C300X_UI_EVENT_MAX_WAITERS; index++) {
        if (events->waiters[index].fd >= 0) {
            count++;
        }
    }
    return count;
}

int c300x_ui_events_timeout_ms(const struct c300x_ui_events *events, time_t now)
{
    int timeout_ms = -1;
    size_t index;

    for (index = 0; index < C300X_UI_EVENT_MAX_WAITERS; index++) {
        if (events->waiters[index].fd >= 0) {
            timeout_ms = min_timeout_ms(
                timeout_ms,
                timeout_until_ms(now, events->waiters[index].deadline)
            );
        }
    }
    return timeout_ms;
}

void c300x_ui_events_notify(
    struct c300x_ui_events *events,
    const char *topic,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
)
{
    size_t index;

    events->revision++;
    snprintf(events->topic, sizeof(events->topic), "%s", topic != NULL ? topic : "");
    for (index = 0; index < C300X_UI_EVENT_MAX_WAITERS; index++) {
        if (events->waiters[index].fd >= 0 && events->revision > events->waiters[index].since) {
            close_waiter(events, index, 1, send_json_fn, ctx);
        }
    }
}

void c300x_ui_events_expire_waiters(
    struct c300x_ui_events *events,
    time_t now,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
)
{
    size_t index;

    for (index = 0; index < C300X_UI_EVENT_MAX_WAITERS; index++) {
        if (events->waiters[index].fd >= 0 && events->waiters[index].deadline <= now) {
            close_waiter(events, index, 0, send_json_fn, ctx);
        }
    }
}

void c300x_ui_events_close_all(
    struct c300x_ui_events *events,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
)
{
    size_t index;

    for (index = 0; index < C300X_UI_EVENT_MAX_WAITERS; index++) {
        close_waiter(events, index, 0, send_json_fn, ctx);
    }
}

int c300x_ui_events_store_waiter(
    struct c300x_ui_events *events,
    int client_fd,
    unsigned long since,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx,
    int *overflowed
)
{
    size_t index;
    size_t oldest_index = C300X_UI_EVENT_MAX_WAITERS;
    time_t oldest_deadline = 0;

    if (overflowed != NULL) {
        *overflowed = 0;
    }
    for (index = 0; index < C300X_UI_EVENT_MAX_WAITERS; index++) {
        if (events->waiters[index].fd < 0) {
            events->waiters[index].fd = client_fd;
            events->waiters[index].since = since;
            events->waiters[index].deadline = time(NULL) + C300X_UI_EVENT_WAIT_SECONDS;
            return 0;
        }
        if (
            oldest_index >= C300X_UI_EVENT_MAX_WAITERS
            || events->waiters[index].deadline < oldest_deadline
        ) {
            oldest_index = index;
            oldest_deadline = events->waiters[index].deadline;
        }
    }
    events->waiter_overflows++;
    if (overflowed != NULL) {
        *overflowed = 1;
    }
    if (oldest_index < C300X_UI_EVENT_MAX_WAITERS) {
        close_waiter(events, oldest_index, 0, send_json_fn, ctx);
        events->waiters[oldest_index].fd = client_fd;
        events->waiters[oldest_index].since = since;
        events->waiters[oldest_index].deadline = time(NULL) + C300X_UI_EVENT_WAIT_SECONDS;
        return 0;
    }
    return 0;
}

int c300x_ui_events_pollfds(
    const struct c300x_ui_events *events,
    struct pollfd *poll_fds,
    int *poll_slots,
    int max_fds
)
{
    int count = 0;
    size_t index;

    if (max_fds <= 0) {
        return 0;
    }
    for (index = 0; index < C300X_UI_EVENT_MAX_WAITERS; index++) {
        if (events->waiters[index].fd >= 0 && count < max_fds) {
            poll_slots[count] = (int)index;
            poll_fds[count].fd = events->waiters[index].fd;
            poll_fds[count].events = POLLIN | POLLRDHUP;
            poll_fds[count].revents = 0;
            count++;
        }
    }
    return count;
}

void c300x_ui_events_handle_pollfds(
    struct c300x_ui_events *events,
    const struct pollfd *poll_fds,
    const int *poll_slots,
    int poll_count,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
)
{
    int index;

    for (index = 0; index < poll_count; index++) {
        if ((poll_fds[index].revents & (POLLIN | C300X_SOCKET_CLOSED_REVENTS)) != 0) {
            close_waiter(events, (size_t)poll_slots[index], 0, send_json_fn, ctx);
        }
    }
}

void c300x_ui_events_status_json(
    const struct c300x_ui_events *events,
    char *out,
    size_t out_len
)
{
    snprintf(
        out,
        out_len,
        "{\"ok\":true,\"revision\":%lu,\"waiters\":%d,\"max_waiters\":%d,\"waiter_overflows\":%lu}\n",
        events->revision,
        c300x_ui_events_waiter_count(events),
        C300X_UI_EVENT_MAX_WAITERS,
        events->waiter_overflows
    );
}

void c300x_ui_events_send_changed(
    const struct c300x_ui_events *events,
    int client_fd,
    int changed,
    c300x_ui_event_send_json_fn send_json_fn,
    void *ctx
)
{
    ui_event_send(events, client_fd, changed, send_json_fn, ctx);
}
