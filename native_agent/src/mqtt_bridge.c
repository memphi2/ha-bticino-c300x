#include "mqtt_bridge.h"
#include "string_util.h"
#include "http_util.h"
#include "time_util.h"

#include <arpa/inet.h>
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define MQTT_CONNECT_TIMEOUT_MS 1500
#ifndef MQTT_RESOLVE_CONNECT_TIMEOUT_MS
#define MQTT_RESOLVE_CONNECT_TIMEOUT_MS 15000
#endif
#define MQTT_PACKET_CONNECT 0x10
#define MQTT_PACKET_CONNACK 0x20
#define MQTT_PACKET_PUBLISH 0x30
#define MQTT_PACKET_SUBSCRIBE 0x82
#define MQTT_PACKET_PINGREQ 0xC0
#define MQTT_PACKET_DISCONNECT 0xE0

enum mqtt_phase { MQTT_CLOSED, MQTT_CONNECT_OUTPUT, MQTT_CONNACK, MQTT_SUBSCRIBE_OUTPUT, MQTT_READY };

static void mqtt_schedule_reconnect(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    time_t now
)
{
    int delay = mqtt->reconnect_delay_seconds;
    if (delay <= 0) {
        delay = config->mqtt_reconnect_initial_seconds;
    }
    if (delay <= 0) {
        delay = 30;
    }
    mqtt->next_connect_at = now + delay;
    delay *= 2;
    if (config->mqtt_reconnect_max_seconds > 0 && delay > config->mqtt_reconnect_max_seconds) {
        delay = config->mqtt_reconnect_max_seconds;
    }
    mqtt->reconnect_delay_seconds = delay;
}

void c300x_mqtt_init(struct c300x_mqtt *mqtt)
{
    memset(mqtt, 0, sizeof(*mqtt));
    mqtt->fd = -1;
}

void c300x_mqtt_close(struct c300x_mqtt *mqtt)
{
    if (mqtt->fd >= 0) {
        close(mqtt->fd);
    }
    c300x_mqtt_connect_cancel(mqtt->connecting);
    mqtt->connecting = NULL;
    mqtt->fd = -1;
    mqtt->connected = 0;
    mqtt->subscribed = 0;
    mqtt->rx_len = 0;
    mqtt->rx_skip = 0;
    memset(&mqtt->output, 0, sizeof(mqtt->output));
    mqtt->phase = MQTT_CLOSED;
    mqtt->connack_used = 0;
    mqtt->connack_deadline_ms = 0;
    mqtt->ping_remaining = 0;
    mqtt->connect_started_at = 0;
}

void c300x_mqtt_reset_retry(struct c300x_mqtt *mqtt)
{
    mqtt->next_connect_at = 0;
    mqtt->reconnect_delay_seconds = 0;
}

static void mqtt_disconnect(struct c300x_mqtt *mqtt, const struct c300x_config *config, time_t now)
{
    /* Startup previously ran entirely within open_if_needed's time snapshot. */
    if (mqtt->phase >= MQTT_CONNECT_OUTPUT && mqtt->phase <= MQTT_SUBSCRIBE_OUTPUT) {
        now = mqtt->connect_started_at;
    }
    c300x_mqtt_close(mqtt);
    mqtt_schedule_reconnect(mqtt, config, now);
}

static size_t write_utf8(unsigned char *out, size_t out_len, const char *value)
{
    size_t len = strlen(value);
    if (len > 65535 || out_len < len + 2) {
        return 0;
    }
    out[0] = (unsigned char)((len >> 8) & 0xff);
    out[1] = (unsigned char)(len & 0xff);
    memcpy(out + 2, value, len);
    return len + 2;
}

static int mqtt_send_packet(struct c300x_mqtt *mqtt, unsigned char packet_type,
    const unsigned char *payload, size_t payload_len)
{
    return c300x_mqtt_output_enqueue(&mqtt->output, packet_type, payload, payload_len,
        c300x_monotonic_ms());
}

static int mqtt_flush_output(struct c300x_mqtt *mqtt, const struct c300x_config *config, time_t now)
{
    int sent = c300x_mqtt_output_flush(&mqtt->output, mqtt->fd, c300x_monotonic_ms());
    if (sent < 0) {
        mqtt_disconnect(mqtt, config, now);
        return 0;
    }
    if (mqtt->ping_remaining > 0) {
        if ((size_t)sent >= mqtt->ping_remaining) {
            mqtt->ping_remaining = 0;
            mqtt->next_ping_at = now + config->mqtt_keepalive_seconds;
        } else {
            mqtt->ping_remaining -= (size_t)sent;
        }
    }
    return 1;
}

static int mqtt_send_connect(struct c300x_mqtt *mqtt, const struct c300x_config *config)
{
    unsigned char payload[1024];
    size_t used = 0;
    unsigned char flags = 0x02;
    unsigned char keepalive_hi;
    unsigned char keepalive_lo;

    if (config->mqtt_username[0] != '\0') {
        flags |= 0x80;
    }
    if (config->mqtt_password[0] != '\0') {
        flags |= 0x40;
    }
    if (config->mqtt_availability_topic[0] != '\0') {
        flags |= 0x04;
        flags |= 0x20;
    }
    {
        size_t written = write_utf8(payload + used, sizeof(payload) - used, "MQTT");
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (used + 4 >= sizeof(payload)) {
        return 0;
    }
    payload[used++] = 4;
    payload[used++] = flags;
    keepalive_hi = (unsigned char)(((unsigned int)config->mqtt_keepalive_seconds >> 8) & 0xff);
    keepalive_lo = (unsigned char)((unsigned int)config->mqtt_keepalive_seconds & 0xff);
    payload[used++] = keepalive_hi;
    payload[used++] = keepalive_lo;
    {
        size_t written = write_utf8(payload + used, sizeof(payload) - used, config->mqtt_client_id);
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (config->mqtt_availability_topic[0] != '\0') {
        size_t written = write_utf8(payload + used, sizeof(payload) - used, config->mqtt_availability_topic);
        if (written == 0) {
            return 0;
        }
        used += written;
        written = write_utf8(payload + used, sizeof(payload) - used, "offline");
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (config->mqtt_username[0] != '\0') {
        size_t written = write_utf8(payload + used, sizeof(payload) - used, config->mqtt_username);
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (config->mqtt_password[0] != '\0') {
        size_t written = write_utf8(payload + used, sizeof(payload) - used, config->mqtt_password);
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (used == 0 || used >= sizeof(payload)) {
        return 0;
    }
    return mqtt_send_packet(mqtt, MQTT_PACKET_CONNECT, payload, used);
}

static int mqtt_send_subscribe(struct c300x_mqtt *mqtt, const struct c300x_config *config)
{
    unsigned char payload[256];
    size_t used = 0;
    if (config->mqtt_command_topic[0] == '\0') {
        return 1;
    }
    payload[used++] = 0;
    payload[used++] = 1;
    {
        size_t written = write_utf8(payload + used, sizeof(payload) - used, config->mqtt_command_topic);
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (used + 1 >= sizeof(payload)) {
        return 0;
    }
    payload[used++] = (unsigned char)config->mqtt_qos;
    return mqtt_send_packet(mqtt, MQTT_PACKET_SUBSCRIBE, payload, used);
}

static int mqtt_publish(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    const char *topic,
    const char *payload,
    int retain,
    time_t now
)
{
    unsigned char buffer[3072];
    size_t topic_len;
    size_t payload_len;
    size_t used = 0;
    unsigned char type = MQTT_PACKET_PUBLISH;

    if (mqtt->fd < 0 || !mqtt->connected || topic[0] == '\0') {
        return 0;
    }
    topic_len = write_utf8(buffer, sizeof(buffer), topic);
    if (topic_len == 0) {
        return 0;
    }
    used = topic_len;
    payload_len = strlen(payload);
    if (used + payload_len >= sizeof(buffer)) {
        return 0;
    }
    memcpy(buffer + used, payload, payload_len);
    used += payload_len;
    if (retain) {
        type |= 0x01;
    }
    if (!mqtt_send_packet(mqtt, type, buffer, used)) {
        return 0;
    }
    return mqtt_flush_output(mqtt, config, now);
}

static int json_raw_field(const char *data_json, char *out, size_t out_len)
{
    const char *key = strstr(data_json, "\"raw\"");
    const char *ptr;
    size_t used = 0;
    if (key == NULL || out_len == 0) {
        return 0;
    }
    ptr = strchr(key, ':');
    if (ptr == NULL) {
        return 0;
    }
    ptr++;
    while (*ptr == ' ' || *ptr == '\t') {
        ptr++;
    }
    if (*ptr != '"') {
        return 0;
    }
    ptr++;
    while (*ptr != '\0' && *ptr != '"') {
        char ch = *ptr++;
        if (ch == '\\' && *ptr != '\0') {
            ch = *ptr++;
        }
        if (used + 1 >= out_len) {
            return 0;
        }
        out[used++] = ch;
    }
    if (*ptr != '"') {
        return 0;
    }
    out[used] = '\0';
    return used > 0;
}

static void mqtt_format_start_date(time_t now, char *payload, size_t payload_len)
{
    struct tm local_time;

    if (
        localtime_r(&now, &local_time) != NULL
        && strftime(payload, payload_len, "%Y-%m-%dT%H:%M:%S", &local_time) > 0
    ) {
        return;
    }
    snprintf(payload, payload_len, "%ld", (long)now);
}

static void mqtt_output_completed(struct c300x_mqtt *mqtt, const struct c300x_config *config)
{
    if (c300x_mqtt_output_pending(&mqtt->output) != 0) {
        return;
    }
    if (mqtt->phase == MQTT_CONNECT_OUTPUT) {
        mqtt->phase = MQTT_CONNACK;
        mqtt->connack_deadline_ms = c300x_monotonic_ms() + MQTT_CONNECT_TIMEOUT_MS;
    } else if (mqtt->phase == MQTT_SUBSCRIBE_OUTPUT) {
        time_t started = mqtt->connect_started_at;
        mqtt->phase = MQTT_READY;
        mqtt->connected = 1;
        mqtt->subscribed = 1;
        (void)mqtt_publish(mqtt, config, config->mqtt_availability_topic, "online", 1, started);
        if (config->mqtt_status_topic[0] != '\0') {
            char payload[32];
            mqtt_format_start_date(started, payload, sizeof(payload));
            (void)mqtt_publish(mqtt, config, config->mqtt_status_topic, payload, 1, started);
        }
    }
}

static void mqtt_receive_connack(struct c300x_mqtt *mqtt, const struct c300x_config *config, time_t now)
{
    ssize_t received = recv(mqtt->fd, mqtt->connack + mqtt->connack_used,
        sizeof(mqtt->connack) - mqtt->connack_used, MSG_DONTWAIT);
    if (received < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
        return;
    }
    if (received <= 0) {
        mqtt_disconnect(mqtt, config, now);
        return;
    }
    mqtt->connack_used += (size_t)received;
    /* Preserve the old per-read 1500ms wait, not a new whole-handshake limit. */
    mqtt->connack_deadline_ms = c300x_monotonic_ms() + MQTT_CONNECT_TIMEOUT_MS;
    if (mqtt->connack_used < sizeof(mqtt->connack)) {
        return;
    }
    if (mqtt->connack[0] != MQTT_PACKET_CONNACK || mqtt->connack[1] != 2 || mqtt->connack[3] != 0) {
        mqtt_disconnect(mqtt, config, now);
        return;
    }
    mqtt->connack_deadline_ms = 0;
    mqtt->reconnect_delay_seconds = config->mqtt_reconnect_initial_seconds;
    mqtt->next_ping_at = mqtt->connect_started_at + config->mqtt_keepalive_seconds;
    mqtt->phase = MQTT_SUBSCRIBE_OUTPUT;
    if (!mqtt_send_subscribe(mqtt, config)) {
        mqtt_disconnect(mqtt, config, now);
    } else if (mqtt_flush_output(mqtt, config, now)) {
        mqtt_output_completed(mqtt, config);
    }
}

void c300x_mqtt_open_if_needed(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    int network_online,
    time_t now
)
{
    if (!config->mqtt_enabled || !network_online) {
        c300x_mqtt_close(mqtt);
        return;
    }
    if (mqtt->fd >= 0 || mqtt->connecting != NULL) {
        return;
    }
    if (mqtt->next_connect_at > now) {
        return;
    }
    if (config->mqtt_host[0] == '\0') {
        mqtt_schedule_reconnect(mqtt, config, now);
        return;
    }
    /* DNS and connect run beside the loop; the wake fd stands in for the
     * socket until the attempt is over. */
    mqtt->connecting = c300x_mqtt_connect_start(config->mqtt_host, config->mqtt_port);
    if (mqtt->connecting == NULL) {
        mqtt_schedule_reconnect(mqtt, config, now);
        return;
    }
    mqtt->connect_started_at = now;
    mqtt->connect_deadline_ms = c300x_monotonic_ms() + MQTT_RESOLVE_CONNECT_TIMEOUT_MS;
}

static void mqtt_connect_finished(struct c300x_mqtt *mqtt, const struct c300x_config *config)
{
    time_t now = mqtt->connect_started_at;
    int fd = c300x_mqtt_connect_finish(mqtt->connecting);
    if (fd == -2) {
        return;
    }
    mqtt->connecting = NULL;
    if (fd < 0) {
        mqtt_schedule_reconnect(mqtt, config, now);
        return;
    }
    mqtt->fd = fd;
    mqtt->phase = MQTT_CONNECT_OUTPUT;
    if (!mqtt_send_connect(mqtt, config)) {
        mqtt_disconnect(mqtt, config, now);
    } else if (mqtt_flush_output(mqtt, config, now)) {
        mqtt_output_completed(mqtt, config);
    }
}

int c300x_mqtt_fd(const struct c300x_mqtt *mqtt)
{
    return mqtt->fd >= 0 ? mqtt->fd : c300x_mqtt_connect_wake_fd(mqtt->connecting);
}

short c300x_mqtt_poll_events(const struct c300x_mqtt *mqtt)
{
    if (mqtt->fd < 0) {
        return mqtt->connecting != NULL ? POLLIN : 0;
    }
    short events = POLLRDHUP;
    if (mqtt->phase == MQTT_CONNACK || mqtt->phase == MQTT_READY) {
        events |= POLLIN;
    }
    if (c300x_mqtt_output_pending(&mqtt->output) > 0) {
        events |= POLLOUT;
    }
    return events;
}

static int mqtt_timer_timeout(const struct c300x_mqtt *mqtt, time_t now)
{
    if (mqtt->fd < 0 || !mqtt->connected || mqtt->next_ping_at <= 0) {
        if (mqtt->next_connect_at > now && mqtt->next_connect_at - now < 3600) {
            return (int)((mqtt->next_connect_at - now) * 1000);
        }
        return -1;
    }
    if (mqtt->ping_remaining > 0) {
        return -1;
    }
    if (mqtt->next_ping_at <= now) {
        return 0;
    }
    if (mqtt->next_ping_at - now > 3600) {
        return 3600000;
    }
    return (int)((mqtt->next_ping_at - now) * 1000);
}

int c300x_mqtt_poll_timeout_ms(const struct c300x_mqtt *mqtt, time_t now)
{
    int timeout = mqtt_timer_timeout(mqtt, now);
    long long mono = c300x_monotonic_ms();
    if (mqtt->connecting != NULL) {
        long long left = mqtt->connect_deadline_ms - mono;
        return left > 0 ? (int)left : 0;
    }
    int output_timeout = c300x_mqtt_output_timeout(&mqtt->output, mono);
    if (output_timeout >= 0 && (timeout < 0 || output_timeout < timeout)) {
        timeout = output_timeout;
    }
    if (mqtt->phase == MQTT_CONNACK) {
        long long remaining = mqtt->connack_deadline_ms - mono;
        int ack_timeout = remaining > 0 ? (int)remaining : 0;
        if (timeout < 0 || ack_timeout < timeout) {
            timeout = ack_timeout;
        }
    }
    return timeout;
}

static size_t mqtt_remaining_length(const unsigned char *buffer, size_t len, size_t *header_len)
{
    size_t multiplier = 1;
    size_t value = 0;
    size_t index = 1;
    while (index < len && index <= 4) {
        unsigned char encoded = buffer[index++];
        value += (encoded & 127) * multiplier;
        if ((encoded & 128) == 0) {
            *header_len = index;
            return value;
        }
        multiplier *= 128;
    }
    *header_len = 0;
    return 0;
}

static void mqtt_handle_publish(struct c300x_mqtt *mqtt, const unsigned char *payload, size_t len)
{
    size_t topic_len;
    size_t topic_start = 2;
    size_t message_start;
    size_t message_len;
    if (len < 3) {
        return;
    }
    topic_len = ((size_t)payload[0] << 8) | payload[1];
    if (topic_start + topic_len > len) {
        return;
    }
    message_start = topic_start + topic_len;
    message_len = len - message_start;
    if (message_len == 0 || message_len >= sizeof(mqtt->pending_command)) {
        return;
    }
    memcpy(mqtt->pending_command, payload + message_start, message_len);
    mqtt->pending_command[message_len] = '\0';
    mqtt->has_pending_command = 1;
}

static void mqtt_process_rx(struct c300x_mqtt *mqtt)
{
    size_t offset = 0;
    while (!mqtt->has_pending_command && offset < mqtt->rx_len) {
        if (mqtt->rx_skip > 0) {
            size_t drop = mqtt->rx_len - offset;
            drop = drop < mqtt->rx_skip ? drop : mqtt->rx_skip;
            offset += drop;
            mqtt->rx_skip -= drop;
            continue;
        }
        if (offset + 2 > mqtt->rx_len) {
            break;
        }
        size_t header_len = 0;
        size_t remaining = mqtt_remaining_length(mqtt->rx_buffer + offset, mqtt->rx_len - offset, &header_len);
        size_t packet_len;
        unsigned char packet_type;
        if (header_len == 0) {
            break;
        }
        packet_len = header_len + remaining;
        /* Never fits (a huge retained command): drop it as it arrives. A
         * reconnect would only get the same retained message again. */
        if (packet_len > sizeof(mqtt->rx_buffer)) {
            mqtt->rx_skip = packet_len;
            continue;
        }
        if (offset + packet_len > mqtt->rx_len) {
            break;
        }
        packet_type = mqtt->rx_buffer[offset] & 0xF0;
        if (packet_type == MQTT_PACKET_PUBLISH) {
            mqtt_handle_publish(mqtt, mqtt->rx_buffer + offset + header_len, remaining);
        }
        offset += packet_len;
    }
    if (offset > 0) {
        memmove(mqtt->rx_buffer, mqtt->rx_buffer + offset, mqtt->rx_len - offset);
        mqtt->rx_len -= offset;
    }
}

void c300x_mqtt_handle_poll(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    short revents,
    time_t now
)
{
    if (mqtt->fd < 0) {
        if (mqtt->connecting != NULL && (revents & POLLIN) != 0) {
            mqtt_connect_finished(mqtt, config);
        }
        return;
    }
    if ((revents & C300X_SOCKET_CLOSED_REVENTS) != 0) {
        mqtt_disconnect(mqtt, config, now);
        return;
    }
    if ((revents & POLLOUT) != 0) {
        if (!mqtt_flush_output(mqtt, config, now)) {
            return;
        }
        mqtt_output_completed(mqtt, config);
    }
    if (mqtt->phase == MQTT_CONNACK && (revents & POLLIN) != 0) {
        mqtt_receive_connack(mqtt, config, now);
        return;
    }
    if (mqtt->phase != MQTT_READY) {
        return;
    }
    if ((revents & POLLIN) != 0) {
        for (;;) {
            ssize_t received;
            if (mqtt->rx_len >= sizeof(mqtt->rx_buffer)) {
                mqtt_disconnect(mqtt, config, now);
                return;
            }
            received = recv(
                mqtt->fd,
                mqtt->rx_buffer + mqtt->rx_len,
                sizeof(mqtt->rx_buffer) - mqtt->rx_len,
                0
            );
            if (received < 0) {
                if (errno == EINTR) {
                    continue;
                }
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    break;
                }
                mqtt_disconnect(mqtt, config, now);
                return;
            }
            if (received == 0) {
                mqtt_disconnect(mqtt, config, now);
                return;
            }
            mqtt->rx_len += (size_t)received;
            mqtt_process_rx(mqtt);
            if (mqtt->has_pending_command) {
                break;
            }
        }
    }
}

void c300x_mqtt_tick(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    time_t now
)
{
    long long mono = c300x_monotonic_ms();
    if (mqtt->connecting != NULL && mqtt->connect_deadline_ms <= mono) {
        now = mqtt->connect_started_at;
        c300x_mqtt_close(mqtt);
        mqtt_schedule_reconnect(mqtt, config, now);
        return;
    }
    if (mqtt->fd < 0) {
        return;
    }
    if (c300x_mqtt_output_timeout(&mqtt->output, mono) == 0
        || (mqtt->phase == MQTT_CONNACK && mqtt->connack_deadline_ms <= mono)) {
        mqtt_disconnect(mqtt, config, now);
        return;
    }
    if (mqtt->connected && mqtt->ping_remaining == 0
        && mqtt->next_ping_at > 0 && mqtt->next_ping_at <= now) {
        if (!mqtt_send_packet(mqtt, MQTT_PACKET_PINGREQ, NULL, 0)) {
            mqtt_disconnect(mqtt, config, now);
            return;
        }
        mqtt->ping_remaining = c300x_mqtt_output_pending(&mqtt->output);
        (void)mqtt_flush_output(mqtt, config, now);
    }
}

void c300x_mqtt_publish_event(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    const char *event_type,
    const char *event_json,
    const char *data_json
)
{
    char raw[C300X_MAX_FRAME_LEN];
    (void)event_type;
    if (!config->mqtt_enabled || mqtt->fd < 0 || !mqtt->connected) {
        return;
    }
    if (config->mqtt_json_event_topic[0] != '\0') {
        (void)mqtt_publish(mqtt, config, config->mqtt_json_event_topic, event_json, 0, time(NULL));
    }
    if (config->mqtt_event_topic[0] != '\0' && json_raw_field(data_json, raw, sizeof(raw))) {
        (void)mqtt_publish(mqtt, config, config->mqtt_event_topic, raw, 0, time(NULL));
    }
}

int c300x_mqtt_take_command(struct c300x_mqtt *mqtt, char *out, size_t out_len)
{
    if (out_len == 0) return 0;
    if (!mqtt->has_pending_command) mqtt_process_rx(mqtt);
    if (!mqtt->has_pending_command || out_len == 0) {
        return 0;
    }
    c300x_copy_string(out, out_len, mqtt->pending_command);
    mqtt->pending_command[0] = '\0';
    mqtt->has_pending_command = 0;
    return 1;
}
