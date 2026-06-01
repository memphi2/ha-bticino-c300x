#include "mqtt_bridge.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define MQTT_CONNECT_TIMEOUT_MS 1500
#define MQTT_PACKET_CONNECT 0x10
#define MQTT_PACKET_CONNACK 0x20
#define MQTT_PACKET_PUBLISH 0x30
#define MQTT_PACKET_SUBSCRIBE 0x82
#define MQTT_PACKET_PINGREQ 0xC0
#define MQTT_PACKET_DISCONNECT 0xE0

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
    mqtt->fd = -1;
    mqtt->connected = 0;
    mqtt->subscribed = 0;
    mqtt->rx_len = 0;
}

void c300x_mqtt_reset_retry(struct c300x_mqtt *mqtt)
{
    mqtt->next_connect_at = 0;
    mqtt->reconnect_delay_seconds = 0;
}

static void mqtt_disconnect(struct c300x_mqtt *mqtt, const struct c300x_config *config, time_t now)
{
    c300x_mqtt_close(mqtt);
    mqtt_schedule_reconnect(mqtt, config, now);
}

static int set_nonblocking(int fd)
{
    int enabled = 1;
    return ioctl(fd, FIONBIO, &enabled) == 0;
}

static int send_all(int fd, const void *data, size_t len)
{
    const unsigned char *ptr = data;
    while (len > 0) {
        ssize_t sent = send(fd, ptr, len, MSG_NOSIGNAL);
        if (sent < 0) {
            if (errno == EINTR) {
                continue;
            }
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                struct pollfd pfd;
                pfd.fd = fd;
                pfd.events = POLLOUT;
                pfd.revents = 0;
                if (poll(&pfd, 1, 500) <= 0) {
                    return 0;
                }
                continue;
            }
            return 0;
        }
        if (sent == 0) {
            return 0;
        }
        ptr += sent;
        len -= (size_t)sent;
    }
    return 1;
}

static size_t encode_remaining_length(unsigned char *out, size_t value)
{
    size_t used = 0;
    do {
        unsigned char encoded = (unsigned char)(value % 128);
        value /= 128;
        if (value > 0) {
            encoded |= 128;
        }
        out[used++] = encoded;
    } while (value > 0 && used < 4);
    return used;
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

static int mqtt_send_packet(int fd, unsigned char packet_type, const unsigned char *payload, size_t payload_len)
{
    unsigned char header[5];
    size_t header_len;
    header[0] = packet_type;
    header_len = 1 + encode_remaining_length(header + 1, payload_len);
    return send_all(fd, header, header_len) && send_all(fd, payload, payload_len);
}

static int socket_connect_timeout(const char *host, uint16_t port)
{
    char port_text[16];
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    struct addrinfo *item;
    int fd = -1;

    snprintf(port_text, sizeof(port_text), "%u", port);
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host, port_text, &hints, &result) != 0) {
        return -1;
    }
    for (item = result; item != NULL; item = item->ai_next) {
        int err = 0;
        socklen_t err_len = sizeof(err);
        struct pollfd pfd;
        fd = socket(item->ai_family, item->ai_socktype, item->ai_protocol);
        if (fd < 0) {
            continue;
        }
        (void)set_nonblocking(fd);
        if (connect(fd, item->ai_addr, item->ai_addrlen) == 0) {
            break;
        }
        if (errno != EINPROGRESS) {
            close(fd);
            fd = -1;
            continue;
        }
        pfd.fd = fd;
        pfd.events = POLLOUT;
        pfd.revents = 0;
        if (poll(&pfd, 1, MQTT_CONNECT_TIMEOUT_MS) <= 0) {
            close(fd);
            fd = -1;
            continue;
        }
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &err_len) != 0 || err != 0) {
            close(fd);
            fd = -1;
            continue;
        }
        break;
    }
    freeaddrinfo(result);
    return fd;
}

static int mqtt_wait_connack(int fd)
{
    unsigned char buffer[4];
    size_t used = 0;
    struct pollfd pfd;
    pfd.fd = fd;
    pfd.events = POLLIN;
    pfd.revents = 0;
    while (used < sizeof(buffer)) {
        ssize_t received;
        if (poll(&pfd, 1, MQTT_CONNECT_TIMEOUT_MS) <= 0) {
            return 0;
        }
        received = recv(fd, buffer + used, sizeof(buffer) - used, 0);
        if (received <= 0) {
            return 0;
        }
        used += (size_t)received;
    }
    return buffer[0] == MQTT_PACKET_CONNACK
        && buffer[1] == 2
        && buffer[3] == 0;
}

static int mqtt_send_connect(int fd, const struct c300x_config *config)
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
    return mqtt_send_packet(fd, MQTT_PACKET_CONNECT, payload, used);
}

static int mqtt_send_subscribe(int fd, const struct c300x_config *config)
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
    return mqtt_send_packet(fd, MQTT_PACKET_SUBSCRIBE, payload, used);
}

static int mqtt_publish(
    struct c300x_mqtt *mqtt,
    const char *topic,
    const char *payload,
    int retain
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
    return mqtt_send_packet(mqtt->fd, type, buffer, used);
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

void c300x_mqtt_open_if_needed(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    int network_online,
    time_t now
)
{
    int fd;
    if (!config->mqtt_enabled || !network_online) {
        c300x_mqtt_close(mqtt);
        return;
    }
    if (mqtt->fd >= 0) {
        return;
    }
    if (mqtt->next_connect_at > now) {
        return;
    }
    if (config->mqtt_host[0] == '\0') {
        mqtt_schedule_reconnect(mqtt, config, now);
        return;
    }
    fd = socket_connect_timeout(config->mqtt_host, config->mqtt_port);
    if (fd < 0) {
        mqtt_schedule_reconnect(mqtt, config, now);
        return;
    }
    if (!mqtt_send_connect(fd, config) || !mqtt_wait_connack(fd)) {
        close(fd);
        mqtt_schedule_reconnect(mqtt, config, now);
        return;
    }
    mqtt->fd = fd;
    mqtt->connected = 1;
    mqtt->reconnect_delay_seconds = config->mqtt_reconnect_initial_seconds;
    mqtt->next_ping_at = now + config->mqtt_keepalive_seconds;
    if (!mqtt_send_subscribe(fd, config)) {
        mqtt_disconnect(mqtt, config, now);
        return;
    }
    mqtt->subscribed = 1;
    (void)mqtt_publish(mqtt, config->mqtt_availability_topic, "online", 1);
    if (config->mqtt_status_topic[0] != '\0') {
        char payload[32];
        mqtt_format_start_date(now, payload, sizeof(payload));
        (void)mqtt_publish(mqtt, config->mqtt_status_topic, payload, 1);
    }
}

int c300x_mqtt_fd(const struct c300x_mqtt *mqtt)
{
    return mqtt->fd;
}

int c300x_mqtt_poll_timeout_ms(const struct c300x_mqtt *mqtt, time_t now)
{
    if (mqtt->fd < 0 || !mqtt->connected || mqtt->next_ping_at <= 0) {
        if (mqtt->next_connect_at > now && mqtt->next_connect_at - now < 3600) {
            return (int)((mqtt->next_connect_at - now) * 1000);
        }
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
    while (offset + 2 <= mqtt->rx_len) {
        size_t header_len = 0;
        size_t remaining = mqtt_remaining_length(mqtt->rx_buffer + offset, mqtt->rx_len - offset, &header_len);
        size_t packet_len;
        unsigned char packet_type;
        if (header_len == 0) {
            break;
        }
        packet_len = header_len + remaining;
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
        return;
    }
    if ((revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
        mqtt_disconnect(mqtt, config, now);
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
            if ((size_t)received == 0) {
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
    unsigned char empty = 0;
    if (mqtt->fd < 0 || !mqtt->connected) {
        return;
    }
    if (mqtt->next_ping_at > 0 && mqtt->next_ping_at <= now) {
        if (!mqtt_send_packet(mqtt->fd, MQTT_PACKET_PINGREQ, &empty, 0)) {
            mqtt_disconnect(mqtt, config, now);
            return;
        }
        mqtt->next_ping_at = now + config->mqtt_keepalive_seconds;
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
        (void)mqtt_publish(mqtt, config->mqtt_json_event_topic, event_json, 0);
    }
    if (config->mqtt_event_topic[0] != '\0' && json_raw_field(data_json, raw, sizeof(raw))) {
        (void)mqtt_publish(mqtt, config->mqtt_event_topic, raw, 0);
    }
}

void c300x_mqtt_publish_raw(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    const char *payload
)
{
    if (!config->mqtt_enabled || mqtt->fd < 0 || !mqtt->connected || config->mqtt_event_topic[0] == '\0') {
        return;
    }
    (void)mqtt_publish(mqtt, config->mqtt_event_topic, payload, 0);
}

int c300x_mqtt_take_command(struct c300x_mqtt *mqtt, char *out, size_t out_len)
{
    if (!mqtt->has_pending_command || out_len == 0) {
        return 0;
    }
    snprintf(out, out_len, "%s", mqtt->pending_command);
    mqtt->pending_command[0] = '\0';
    mqtt->has_pending_command = 0;
    return 1;
}
