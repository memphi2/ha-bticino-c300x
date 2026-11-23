#include "display_alerts.h"
#include "device_detect.h"
#include "http_util.h"
#include "json_util.h"
#include "sha256.h"
#include "time_util.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

struct alert_payload {
    char id[33], notification_id[65], revision[33], severity[8];
    char title[321], message[2001];
    int wake_duration, sound_duration, expires_in;
};

static void fail(int fd, int status, const char *error)
{
    char body[128];
    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}\n", error);
    c300x_http_send_json(fd, status, "Display Alert Error", body);
}

enum alert_outcome { DELIVERY_FAILED, TRANSPORT_ACCEPTED, DISPLAY_PROTECTED };

static void result(int fd, int outcome)
{
    if (outcome == DISPLAY_PROTECTED)
        c300x_http_send_json(fd, 200, "OK",
            "{\"ok\":true,\"accepted\":false,\"suppressed\":true,\"reason\":\"display_protected\"}\n");
    else if (outcome == TRANSPORT_ACCEPTED)
        c300x_http_send_json(fd, 200, "OK", "{\"ok\":true,\"accepted\":true}\n");
    else fail(fd, 503, "display_alerts_delivery_failed");
}

static const char *space(const char *p)
{
    return p + strspn(p, " \t\r\n");
}

static int exact_fields(const char *body)
{
    static const char *const fields[] = {"id", "notification_id", "revision", "severity",
        "title", "message", "wake_duration", "sound_duration", "expires_in"};
    unsigned seen = 0;
    if (!c300x_json_object_valid(body)) return 0;
    const char *end = body + strlen(body), *p = space(body) + 1;
    while (*(p = space(p)) != '}') {
        char key[32];
        if (!c300x_json_decode_string(p, end, key, sizeof(key), &p)) return 0;
        size_t i;
        for (i = 0; i < sizeof(fields) / sizeof(fields[0]); i++)
            if (!strcmp(key, fields[i])) break;
        if (i == sizeof(fields) / sizeof(fields[0]) || (seen & (1u << i))) return 0;
        seen |= 1u << i;
        p = c300x_json_skip_value(space(p) + 1, end);
        if (!p) return 0;
        p = space(p);
        if (*p == ',') p++;
    }
    return seen == (1u << (sizeof(fields) / sizeof(fields[0]))) - 1;
}

static int hex_id(const char *value)
{
    return strlen(value) == 32 && strspn(value, "0123456789abcdef") == 32;
}

static int unicode_length(const char *value)
{
    int count = 0;
    /* The shared JSON decoder already rejects invalid UTF-8 and surrogates. */
    for (const unsigned char *p = (const unsigned char *)value; *p; p++)
        if ((*p & 0xc0) != 0x80) count++;
    return count;
}

static int parse_payload(const char *body, struct alert_payload *payload)
{
    if (!exact_fields(body)) return 0;
#define STRING_FIELD(name) \
    if (c300x_json_string_field_checked(body, #name, payload->name, sizeof(payload->name)) != 1) return 0
    STRING_FIELD(id);
    STRING_FIELD(notification_id);
    STRING_FIELD(revision);
    STRING_FIELD(severity);
    STRING_FIELD(title);
    STRING_FIELD(message);
#undef STRING_FIELD
    if (!hex_id(payload->id) || !hex_id(payload->revision)
        || !payload->notification_id[0]
        || strspn(payload->notification_id, "abcdefghijklmnopqrstuvwxyz0123456789_-")
            != strlen(payload->notification_id)
        || (strcmp(payload->severity, "info") && strcmp(payload->severity, "warning")
            && strcmp(payload->severity, "error"))
        || unicode_length(payload->title) > 80 || unicode_length(payload->message) > 500)
        return 0;
    return c300x_json_int_field(body, "wake_duration", &payload->wake_duration)
        && payload->wake_duration >= 0 && payload->wake_duration <= 300
        && c300x_json_int_field(body, "sound_duration", &payload->sound_duration)
        && payload->sound_duration >= 0 && payload->sound_duration <= 300
        && c300x_json_int_field(body, "expires_in", &payload->expires_in)
        && payload->expires_in >= 1 && payload->expires_in <= 604800;
}

static int serialize(const struct alert_payload *payload, char *body, size_t capacity)
{
    char title[80 * 6 + 3], message[500 * 6 + 3];
    c300x_json_string(payload->title, title, sizeof(title));
    c300x_json_string(payload->message, message, sizeof(message));
    int size = snprintf(body, capacity,
        "{\"id\":\"%s\",\"notification_id\":\"%s\",\"revision\":\"%s\",\"severity\":\"%s\","
        "\"title\":%s,\"message\":%s,\"wake_duration\":%d,\"sound_duration\":%d,\"expires_in\":%d}",
        payload->id, payload->notification_id, payload->revision, payload->severity,
        title, message, payload->wake_duration, payload->sound_duration, payload->expires_in);
    return size > 0 && (size_t)size < capacity;
}

static int deliver(int fd, const char *body, int expires_in)
{
    char response[4608];
    struct timespec now;
    if (clock_gettime(CLOCK_REALTIME, &now) != 0) return 0;
    long long timestamp = (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
    int remaining = expires_in < 5 ? expires_in * 1000 : C300X_DISPLAY_ALERTS_DELIVERY_MS;
    char suffix[192];
    int tail = snprintf(suffix, sizeof(suffix),
        ",\"remaining_ms\":%d,\"expires\":%lld,\"message_expires\":%lld}\n",
        remaining, timestamp + remaining, timestamp + (long long)expires_in * 1000);
    size_t length = strlen(body) - 1;
    int size = snprintf(response, sizeof(response),
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        "Cache-Control: no-store\r\nConnection: close\r\nContent-Length: %zu\r\n\r\n%.*s%s",
        length + (size_t)tail, (int)length, body, suffix);
    /* A successful write means queued, not GUI readback or physical effects. */
    return size > 0 && (size_t)size < sizeof(response)
        && c300x_http_write(fd, response, (size_t)size);
}

void c300x_display_alerts_init(struct c300x_display_alerts *alerts)
{
    memset(alerts, 0, sizeof(*alerts));
    alerts->gui_fd = -1;
    alerts->sound_supported = c300x_device_model() != C300X_DEVICE_MODEL_C100X;
}

int c300x_display_alerts_prepare(const struct c300x_display_alerts *alerts, struct pollfd *fds)
{
    fds[0] = (struct pollfd){.fd = alerts->gui_fd, .events = POLLIN | POLLRDHUP};
    /* Receipts expire lazily: an idle listener adds no timer wakeups. */
    return -1;
}

void c300x_display_alerts_close(struct c300x_display_alerts *alerts)
{
    close_agent_socket(alerts->gui_fd);
    alerts->gui_fd = -1;
    alerts->gui_protected = 0;
}

void c300x_display_alerts_tick(struct c300x_display_alerts *alerts, const struct pollfd *fds)
{
    if (alerts->gui_fd >= 0 && fds[0].fd == alerts->gui_fd
        && (fds[0].revents & (POLLIN | C300X_SOCKET_CLOSED_REVENTS)))
        c300x_display_alerts_close(alerts);
}

static void prune_listener(struct c300x_display_alerts *alerts)
{
    struct pollfd fd;
    c300x_display_alerts_prepare(alerts, &fd);
    if (poll(&fd, 1, 0) > 0) c300x_display_alerts_tick(alerts, &fd);
}

int c300x_display_alerts_handle_ui(struct c300x_display_alerts *alerts, int fd,
    const struct request *request)
{
    if (strcmp(request->method, "GET")) { fail(fd, 405, "method_not_allowed"); return 1; }
    int protected = strcmp(request->query, "protected=1") == 0;
    if ((request->query[0] && !protected) || request->body_len) {
        fail(fd, 400, "invalid_alert_poll"); return 1;
    }
    prune_listener(alerts);
    if (alerts->gui_fd >= 0) { fail(fd, 409, "display_alerts_listener_busy"); return 1; }
    alerts->gui_fd = fd;
    alerts->gui_protected = protected;
    return 0;
}

void c300x_display_alerts_handle_api(struct c300x_display_alerts *alerts, int fd,
    const struct request *request)
{
    struct alert_payload payload = {0};
    char body[4096], digest[65];
    if (strcmp(request->method, "POST")) { fail(fd, 405, "method_not_allowed"); return; }
    if (request->body_len > C300X_DISPLAY_ALERTS_MAX_BODY) {
        fail(fd, 413, "display_alert_too_large"); return;
    }
    if (request->query[0] || !parse_payload(request->body, &payload)) {
        fail(fd, 400, "invalid_display_alert"); return;
    }
    if (payload.sound_duration > 0 && !alerts->sound_supported) {
        fail(fd, 400, "display_alert_sound_unsupported"); return;
    }
    if (!serialize(&payload, body, sizeof(body))
        || !c300x_sha256_bytes_hex((const unsigned char *)body, strlen(body), digest, sizeof(digest))) {
        fail(fd, 503, "display_alerts_unavailable"); return;
    }
    long long now = c300x_monotonic_ms();
    struct c300x_display_alert_receipt *free_slot = NULL;
    for (size_t i = 0; i < C300X_DISPLAY_ALERTS_DEDUP_SLOTS; i++) {
        struct c300x_display_alert_receipt *receipt = &alerts->receipts[i];
        if (receipt->deadline_ms <= now) {
            if (!free_slot) free_slot = receipt;
        } else if (!strcmp(receipt->id, payload.id)) {
            if (strcmp(receipt->digest, digest)) fail(fd, 409, "display_alert_id_conflict");
            else result(fd, receipt->outcome);
            return;
        }
    }
    prune_listener(alerts);
    if (alerts->gui_fd < 0) { fail(fd, 503, "display_alerts_gui_unavailable"); return; }
    if (!free_slot) { fail(fd, 503, "display_alerts_dedup_full"); return; }
    memcpy(free_slot->id, payload.id, sizeof(free_slot->id));
    memcpy(free_slot->digest, digest, sizeof(free_slot->digest));
    free_slot->deadline_ms = now + C300X_DISPLAY_ALERTS_DEDUP_MS;
    /* Protection belongs to this live socket, never to a cached GUI flag. */
    if (alerts->gui_protected) {
        free_slot->outcome = DISPLAY_PROTECTED;
    } else {
        free_slot->outcome = deliver(alerts->gui_fd, body, payload.expires_in)
            ? TRANSPORT_ACCEPTED : DELIVERY_FAILED;
        c300x_display_alerts_close(alerts);
    }
    result(fd, free_slot->outcome);
}
