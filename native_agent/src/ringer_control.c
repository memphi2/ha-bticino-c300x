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
    control->id[0] = '\0';
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
        fail(control->client_fd, 504, "ringer_gui_timeout");
        finish(control);
    }
}

int c300x_ringer_control_next(
    struct c300x_ringer_control *control, int fd, const char *completed, int muted,
    c300x_ringer_apply_fn apply, void *ctx
)
{
    c300x_ringer_control_expire(control);
    if (completed[0] != '\0') {
        if (control->client_fd < 0 || strcmp(completed, control->id) != 0) {
            fail(fd, 409, "ringer_gui_stale_ack");
            return 1;
        }
        if (muted != control->command.muted) {
            fail(control->client_fd, 502, "ringer_gui_not_applied");
        } else {
            apply(control->client_fd, &control->command, ctx);
        }
        finish(control);
    }
    if (control->gui_fd >= 0 || control->client_fd >= 0) {
        fail(fd, 409, "ringer_gui_busy");
        return 1;
    }
    /* A single sleeping connection, without periodic expiry or device reads. */
    control->gui_fd = fd;
    return 0;
}

void c300x_ringer_control_request(
    struct c300x_ringer_control *control, int fd, const struct c300x_ringer_command *command
)
{
    char body[192];
    char response[512];
    int length;
    c300x_ringer_control_expire(control);
    if (control->client_fd >= 0) {
        fail(fd, 409, "ringer_gui_busy");
        return;
    }
    if (control->gui_fd < 0) {
        fail(fd, 503, "ringer_gui_unavailable");
        return;
    }
    if (!new_id(control->id)) {
        fail(fd, 500, "ringer_gui_id_failed");
        return;
    }
    snprintf(body, sizeof(body),
             "{\"ok\":true,\"id\":\"%s\",\"muted\":%s,\"expires\":%lld}\n",
             control->id, command->muted ? "true" : "false",
             ((long long)time(NULL) + C300X_RINGER_CONTROL_TIMEOUT_MS / 1000) * 1000);
    length = snprintf(response, sizeof(response),
                      "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                      "Cache-Control: no-store\r\nConnection: close\r\nContent-Length: %zu\r\n\r\n%s",
                      strlen(body), body);
    if (!send_all_bytes(control->gui_fd, response, (size_t)length)) {
        close_agent_socket(control->gui_fd);
        control->gui_fd = -1;
        fail(fd, 503, "ringer_gui_unavailable");
        return;
    }
    close_agent_socket(control->gui_fd);
    control->gui_fd = -1;
    control->client_fd = fd;
    control->command = *command;
    control->deadline_ms = c300x_monotonic_ms() + C300X_RINGER_CONTROL_TIMEOUT_MS;
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
