#include "touch_tone.h"
#include "http_util.h"
#include "time_util.h"
#include "json_util.h"

#include <stdio.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static void fail(int fd, int status, const char *error)
{
    char body[128];
    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}\n", error);
    c300x_http_send_json(fd, status, "Touch Tone Error", body);
}

static void finish(struct c300x_touch_tone *tone)
{
    close_agent_socket(tone->client_fd);
    tone->client_fd = -1;
    tone->id[0] = '\0';
    tone->deadline_ms = 0;
}

static void notify(struct c300x_touch_tone *tone, int confirmed)
{
    int available = tone->enabled >= 0 && (tone->gui_fd >= 0 || tone->client_fd >= 0);
    enum c300x_setting_transition transition = c300x_setting_observe(
        &tone->state, available, confirmed ? (uint64_t)tone->enabled : tone->state.last_valid);
    int changed = transition == C300X_SETTING_CHANGED;
    if (tone->notify) tone->notify(tone->ctx, changed);
}

void c300x_touch_tone_init(struct c300x_touch_tone *tone, void (*notify)(void *, int), void *ctx)
{
    memset(tone, 0, sizeof(*tone));
    tone->gui_fd = tone->client_fd = tone->enabled = -1;
    tone->revision = -1;
    tone->notify = notify;
    tone->ctx = ctx;
}

void c300x_touch_tone_status(const struct c300x_touch_tone *tone, char *body, size_t size)
{
    int available = tone->enabled >= 0 && (tone->gui_fd >= 0 || tone->client_fd >= 0);
    snprintf(body, size, "{\"ok\":true,\"available\":%s,\"enabled\":%s}\n",
             available ? "true" : "false", available ? (tone->enabled ? "true" : "false") : "null");
}

int c300x_touch_tone_report(struct c300x_touch_tone *tone, const char *session, int revision, int enabled)
{
    if (!session[0] || strcmp(session, tone->session)) return 0;
    if (revision <= tone->revision) return 1;
    tone->revision = revision;
    if (tone->enabled != enabled) {
        tone->enabled = enabled;
        notify(tone, 1);
    }
    return 1;
}

void c300x_touch_tone_request(struct c300x_touch_tone *tone, int fd, int enabled)
{
    char body[192];
    unsigned char random[16];
    if (tone->client_fd >= 0) { fail(fd, 409, "touch_tone_busy"); return; }
    if (tone->gui_fd < 0) { fail(fd, 503, "touch_tone_gui_unavailable"); return; }
    FILE *file = fopen("/dev/urandom", "rb");
    size_t count = file ? fread(random, 1, sizeof(random), file) : 0;
    if (file) fclose(file);
    if (count != sizeof(random)) { fail(fd, 500, "touch_tone_id_failed"); return; }
    for (size_t i = 0; i < sizeof(random); i++)
        snprintf(tone->id + i * 2, 3, "%02x", random[i]);
    snprintf(body, sizeof(body), "{\"ok\":true,\"id\":\"%s\",\"enabled\":%s,\"expires\":%lld}\n",
             tone->id, enabled ? "true" : "false", ((long long)time(NULL) + 5) * 1000);
    c300x_http_send_json(tone->gui_fd, 200, "OK", body);
    close_agent_socket(tone->gui_fd);
    tone->gui_fd = -1;
    tone->client_fd = fd;
    tone->requested = enabled;
    tone->deadline_ms = c300x_monotonic_ms() + 5000;
}

int c300x_touch_tone_next(struct c300x_touch_tone *tone, int fd, const char *query)
{
    char enabled_text[8], completed[64], body[128], session[64], revision_text[16];
    query_param_value(query, "enabled", enabled_text, sizeof(enabled_text));
    query_param_value(query, "completed", completed, sizeof(completed));
    query_param_value(query, "session", session, sizeof(session));
    query_param_value(query, "revision", revision_text, sizeof(revision_text));
    long revision = strtol(revision_text, NULL, 10);
    if ((strcmp(enabled_text, "0") && strcmp(enabled_text, "1"))
        || strlen(session) != 32 || strspn(session, "0123456789abcdef") != 32
        || !revision_text[0] || strspn(revision_text, "0123456789") != strlen(revision_text)
        || revision < 0 || revision >= INT_MAX
        || (completed[0] && (strlen(completed) != 32 || strspn(completed, "0123456789abcdef") != 32))) {
        fail(fd, 400, "invalid_touch_tone_ack");
        return 1;
    }
    if (tone->gui_fd >= 0) { fail(fd, 409, "touch_tone_busy"); return 1; }
    if (!completed[0] && strcmp(session, tone->session) == 0 && revision <= tone->revision) {
        fail(fd, 409, "touch_tone_stale_ack");
        return 1;
    }
    if (completed[0]) {
        if (tone->client_fd < 0 || strcmp(completed, tone->id)
            || strcmp(session, tone->session)
            || c300x_monotonic_ms() >= tone->deadline_ms) {
            fail(fd, 409, "touch_tone_stale_ack");
            return 1;
        }
    } else if (tone->client_fd >= 0) {
        fail(fd, 409, "touch_tone_busy");
        return 1;
    }
    tone->gui_fd = fd;
    if (strcmp(session, tone->session) || revision > tone->revision) {
        memcpy(tone->session, session, sizeof(tone->session));
        tone->revision = (int)revision;
        tone->enabled = enabled_text[0] == '1';
    }
    if (completed[0]) {
        if ((enabled_text[0] == '1') == tone->requested && tone->enabled == tone->requested) {
            c300x_touch_tone_status(tone, body, sizeof(body));
            c300x_http_send_json(tone->client_fd, 200, "OK", body);
        } else fail(tone->client_fd, 409, "touch_tone_not_applied");
        finish(tone);
    }
    notify(tone, 1);
    return 0;
}

int c300x_touch_tone_prepare(const struct c300x_touch_tone *tone, struct pollfd *fds)
{
    fds[0] = (struct pollfd){.fd = tone->gui_fd, .events = POLLIN | POLLRDHUP};
    fds[1] = (struct pollfd){.fd = tone->client_fd, .events = POLLIN | POLLRDHUP};
    if (tone->client_fd < 0) return -1;
    long long remaining = tone->deadline_ms - c300x_monotonic_ms();
    return remaining <= 0 ? 0 : (int)remaining;
}

void c300x_touch_tone_tick(struct c300x_touch_tone *tone, const struct pollfd *fds)
{
    if (tone->gui_fd >= 0 && fds[0].fd == tone->gui_fd
        && (fds[0].revents & (POLLIN | C300X_SOCKET_CLOSED_REVENTS))) {
        close_agent_socket(tone->gui_fd);
        tone->gui_fd = -1;
        tone->enabled = -1;
        notify(tone, 0);
    }
    if (tone->client_fd >= 0 && fds[1].fd == tone->client_fd
        && (fds[1].revents & (POLLIN | C300X_SOCKET_CLOSED_REVENTS))) {
        finish(tone);
        notify(tone, 0);
    }
    if (tone->client_fd >= 0 && c300x_monotonic_ms() >= tone->deadline_ms) {
        fail(tone->client_fd, 504, "touch_tone_gui_timeout");
        finish(tone);
        tone->enabled = -1;
        notify(tone, 0);
    }
}

void c300x_touch_tone_close(struct c300x_touch_tone *tone)
{
    if (tone->gui_fd >= 0) close_agent_socket(tone->gui_fd);
    tone->gui_fd = -1;
    if (tone->client_fd >= 0) {
        fail(tone->client_fd, 503, "touch_tone_gui_unavailable");
        finish(tone);
    }
}

void c300x_touch_tone_handle_api(struct c300x_touch_tone *tone, int fd, const struct request *request)
{
    char body[128];
    int enabled;
    if (strcmp(request->method, "GET") == 0) {
        c300x_touch_tone_status(tone, body, sizeof(body));
        c300x_http_send_json(fd, 200, "OK", body);
    } else if (strcmp(request->method, "POST") == 0) {
        if (!c300x_json_bool_field(request->body, "enabled", &enabled)) {
            fail(fd, 400, "invalid_touch_tone_enabled");
            return;
        }
        c300x_touch_tone_request(tone, fd, enabled);
    } else fail(fd, 405, "method_not_allowed");
}

int c300x_touch_tone_handle_ui(struct c300x_touch_tone *tone, int fd, const struct request *request)
{
    int enabled, revision;
    char session[64];
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/ui/touch-tone/next") == 0)
        return c300x_touch_tone_next(tone, fd, request->query);
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/ui/touch-tone/state") == 0) {
        if (!c300x_json_bool_field(request->body, "enabled", &enabled)
            || !c300x_json_int_field(request->body, "revision", &revision) || revision < 0 || revision == INT_MAX
            || c300x_json_string_field_checked(request->body, "session", session, sizeof(session)) <= 0
            || strlen(session) != 32 || strspn(session, "0123456789abcdef") != 32) {
            fail(fd, 400, "invalid_touch_tone_enabled");
            return 1;
        }
        if (!c300x_touch_tone_report(tone, session, revision, enabled)) {
            fail(fd, 409, "touch_tone_stale_session");
            return 1;
        }
        c300x_http_send_json(fd, 200, "OK", "{\"ok\":true}\n");
    } else fail(fd, 405, "method_not_allowed");
    return 1;
}
