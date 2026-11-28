#include "ringer_control.h"

#include "http_util.h"
#include "time_util.h"

#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>

static void fail(int fd, int status, const char *error)
{
    char body[128];
    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}\n", error);
    c300x_http_send_json(fd, status, "Ringer Control Error", body);
}

static void finish(struct c300x_ringer_control *control)
{
    close_agent_socket(control->client_fd);
    control->client_fd = -1;
    control->deadline_ms = 0;
    control->gui_confirmed = 0;
    control->device_confirmed = 0;
    control->event_verified = 0;
    control->apply = NULL;
    control->apply_ctx = NULL;
    control->id[0] = '\0';
    control->picture.field = PICTURE_NONE;
}

static int new_id(char *id)
{
    unsigned char bytes[16];
    FILE *file = fopen("/dev/urandom", "rb");
    size_t count;
    if (file == NULL) {
        return 0;
    }
    count = fread(bytes, 1, sizeof(bytes), file);
    fclose(file);
    if (count != sizeof(bytes)) {
        return 0;
    }
    for (size_t i = 0; i < sizeof(bytes); i++) {
        snprintf(id + i * 2, 3, "%02x", bytes[i]);
    }
    return 1;
}

void c300x_ringer_control_init(struct c300x_ringer_control *control)
{
    memset(control, 0, sizeof(*control));
    control->gui_fd = -1;
    control->client_fd = -1;
    control->gui_muted = -1;
}

static int send_command(struct c300x_ringer_control *control, const char *body)
{
    char response[512];
    int length = snprintf(response, sizeof(response),
                          "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                          "Cache-Control: no-store\r\nConnection: close\r\nContent-Length: %zu\r\n\r\n%s",
                          strlen(body), body);
    int sent = c300x_http_write(control->gui_fd, response, (size_t)length);
    close_agent_socket(control->gui_fd);
    control->gui_fd = -1;
    return sent;
}

/* Only into a sleeping GUI request, never past a command or another sync. */
static void push_sync(struct c300x_ringer_control *control)
{
    char body[128];
    long long now = c300x_monotonic_ms();
    if (!control->sync_wanted || control->gui_fd < 0 || control->client_fd >= 0
        || (control->sync_id[0] && now < control->sync_deadline_ms) || !new_id(control->sync_id)) {
        return;
    }
    snprintf(body, sizeof(body), "{\"ok\":true,\"id\":\"%s\",\"muted\":false,\"expires\":%lld}\n",
             control->sync_id, ((long long)time(NULL) + C300X_RINGER_CONTROL_TIMEOUT_MS / 1000) * 1000);
    control->sync_wanted = 0;
    control->sync_deadline_ms = now + C300X_RINGER_CONTROL_TIMEOUT_MS;
    (void)send_command(control, body);
}

void c300x_ringer_control_observe(struct c300x_ringer_control *control, int muted, int sync)
{
    if (muted) {
        control->gui_muted = 1;
        control->sync_wanted = 0;
    } else if (sync && control->client_fd < 0 && control->gui_muted != 0) {
        control->sync_wanted = 1;
        push_sync(control);
    }
}

int c300x_gui_supports_picture(const struct c300x_ringer_control *control)
{
    /* A dispatched command temporarily owns the slot instead of the sleeping GUI. */
    return control->picture_supported && (control->gui_fd >= 0 || control->client_fd >= 0);
}

int c300x_ringer_control_timeout_ms(const struct c300x_ringer_control *control)
{
    long long remaining;
    if (control->client_fd < 0) {
        return -1;
    }
    remaining = control->deadline_ms - c300x_monotonic_ms();
    return remaining <= 0 ? 0 : (int)remaining;
}

void c300x_ringer_control_expire(struct c300x_ringer_control *control)
{
    if (c300x_ringer_control_timeout_ms(control) == 0) {
        /* Missing UDP and idempotent commands get one final verification. */
        if (control->gui_confirmed && control->apply != NULL
            && control->apply(control->client_fd, &control->command, control->apply_ctx)) {
            finish(control);
            return;
        }
        if (control->picture.field) fail(control->client_fd, 504, "picture_gui_timeout");
        else fail(control->client_fd, control->gui_confirmed ? 409 : 504,
             control->gui_confirmed ? "ringer_not_applied" : "ringer_gui_timeout");
        finish(control);
    }
}

static void verify_event(struct c300x_ringer_control *control)
{
    if (!control->gui_confirmed || !control->device_confirmed || control->event_verified) {
        return;
    }
    /* Bound duplicate/stale event traffic to one read plus the deadline check. */
    control->event_verified = 1;
    if (control->apply(control->client_fd, &control->command, control->apply_ctx)) {
        finish(control);
    }
}

int c300x_ringer_control_next(
    struct c300x_ringer_control *control, int fd, const char *query,
    c300x_ringer_apply_fn apply, void *ctx
)
{
    char completed[64];
    char muted_text[16];
    char picture_id[64], version[8];
    int muted = -1;
    query_param_value(query, "completed", completed, sizeof(completed));
    query_param_value(query, "muted", muted_text, sizeof(muted_text));
    if (strcmp(muted_text, "0") == 0 || strcmp(muted_text, "1") == 0) {
        muted = muted_text[0] == '1';
    }
    if (completed[0] != '\0' && (strlen(completed) != 32 || muted < 0)) {
        c300x_http_send_json(fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_ringer_gui_ack\"}\n");
        return 1;
    }
    c300x_ringer_control_expire(control);
    query_param_value(query, "picture_id", picture_id, sizeof(picture_id));
    if (*picture_id) {
        if (*completed || control->client_fd < 0 || !control->picture.field || strcmp(picture_id, control->id)) {
            fail(fd, 409, "picture_stale_ack");
            return 1;
        }
        picture_reply(control->client_fd, &control->picture, query);
        finish(control);
    }
    if (completed[0] != '\0' && control->sync_id[0] && strcmp(completed, control->sync_id) == 0) {
        /* The sync's ack: nobody waits for it, and it is not repeated. */
        control->sync_id[0] = '\0';
        control->sync_wanted = 0;
        control->gui_muted = muted;
    } else if (completed[0] != '\0') {
        if (control->client_fd < 0 || control->gui_confirmed || control->picture.field
            || strcmp(completed, control->id) != 0) {
            fail(fd, 409, "ringer_gui_stale_ack");
            return 1;
        }
        if (muted != control->command.muted) {
            fail(control->client_fd, 502, "ringer_gui_not_applied");
            finish(control);
        } else {
            control->gui_muted = muted;
            control->gui_confirmed = 1;
            control->apply = apply;
            control->apply_ctx = ctx;
            /* An early read broadcasts the old mute state back into the GUI. */
            verify_event(control);
        }
    }
    if (control->gui_fd >= 0 || (control->client_fd >= 0 && !control->gui_confirmed)) {
        fail(fd, 409, "ringer_gui_busy");
        return 1;
    }
    /* A single sleeping connection, without periodic expiry or device reads. */
    control->gui_fd = fd;
    query_param_value(query, "picture", version, sizeof(version));
    control->picture_supported = !strcmp(version, "1");
    push_sync(control);
    return 0;
}

int c300x_ringer_control_confirm(
    struct c300x_ringer_control *control, int muted
)
{
    c300x_ringer_control_expire(control);
    if (control->client_fd < 0 || control->picture.field) {
        return 0;
    }
    control->device_confirmed = muted == control->command.muted;
    if (!control->device_confirmed) {
        return 0;
    }
    verify_event(control);
    return 1;
}

static void gui_request(
    struct c300x_ringer_control *control, int fd, const struct c300x_ringer_command *command,
    struct picture_command picture
)
{
    char body[192];
    c300x_ringer_control_expire(control);
    if (control->client_fd >= 0) {
        fail(fd, 409, picture.field ? "picture_gui_busy" : "ringer_gui_busy");
        return;
    }
    if (control->gui_fd < 0 || (picture.field && !control->picture_supported)) {
        fail(fd, 503, picture.field ? "picture_gui_unavailable" : "ringer_gui_unavailable");
        return;
    }
    if (!new_id(control->id)) {
        fail(fd, 500, "ringer_gui_id_failed");
        return;
    }
    if (picture.field)
        snprintf(body, sizeof(body), "{\"ok\":true,\"id\":\"%s\",\"picture\":\"%s\",\"value\":%d,\"expires\":%lld}\n",
                 control->id, picture_name(picture.field), picture.value,
                 ((long long)time(NULL) + C300X_RINGER_CONTROL_TIMEOUT_MS / 1000) * 1000);
    else snprintf(body, sizeof(body),
             "{\"ok\":true,\"id\":\"%s\",\"muted\":%s,\"expires\":%lld}\n",
             control->id, command->muted ? "true" : "false",
             ((long long)time(NULL) + C300X_RINGER_CONTROL_TIMEOUT_MS / 1000) * 1000);
    if (!send_command(control, body)) {
        fail(fd, 503, "ringer_gui_unavailable");
        return;
    }
    control->client_fd = fd;
    if (command) control->command = *command;
    control->picture = picture;
    control->deadline_ms = c300x_monotonic_ms() + C300X_RINGER_CONTROL_TIMEOUT_MS;
}

void c300x_ringer_control_request(struct c300x_ringer_control *control, int fd,
                                  const struct c300x_ringer_command *command)
{
    gui_request(control, fd, command, (struct picture_command){0});
}

void c300x_gui_picture_request(struct c300x_ringer_control *control, int fd, struct picture_command command)
{
    gui_request(control, fd, NULL, command);
}

int c300x_ringer_control_pollfds(const struct c300x_ringer_control *control, struct pollfd *fds)
{
    int sockets[] = {control->gui_fd, control->client_fd};
    int count = 0;
    for (size_t i = 0; i < sizeof(sockets) / sizeof(sockets[0]); i++) {
        if (sockets[i] >= 0) {
            fds[count].fd = sockets[i];
            fds[count].events = POLLIN | POLLRDHUP;
            fds[count++].revents = 0;
        }
    }
    return count;
}

void c300x_ringer_control_handle_pollfds(struct c300x_ringer_control *control, const struct pollfd *fds, int count)
{
    for (int i = 0; i < count; i++) {
        /* These connections accept no further request bytes. */
        if ((fds[i].revents & (POLLIN | C300X_SOCKET_CLOSED_REVENTS)) == 0) {
            continue;
        }
        if (fds[i].fd == control->gui_fd) {
            close_agent_socket(control->gui_fd);
            control->gui_fd = -1;
        } else if (fds[i].fd == control->client_fd) {
            finish(control);
        }
    }
}

void c300x_ringer_control_close(struct c300x_ringer_control *control)
{
    if (control->gui_fd >= 0) {
        close_agent_socket(control->gui_fd);
        control->gui_fd = -1;
    }
    if (control->client_fd >= 0) {
        fail(control->client_fd, 503, "ringer_gui_unavailable");
        finish(control);
    }
}
