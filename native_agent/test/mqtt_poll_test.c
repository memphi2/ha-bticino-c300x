#include <assert.h>
#include <fcntl.h>
#include "../src/mqtt_bridge.c"

static long long clock_ms = 1000;
static unsigned char wire[30000];
static size_t wire_size, allowance = 30000;
static int blocked, fail_send, send_calls;

long long c300x_monotonic_ms(void) { return clock_ms; }
void set_fd_cloexec(int fd) { assert(fd >= 0); }

ssize_t __wrap_send(int fd, const void *data, size_t len, int flags)
{
    assert(fd >= 0 && (flags & MSG_DONTWAIT));
    send_calls++;
    if (blocked || fail_send) {
        errno = fail_send ? EPIPE : EAGAIN;
        return -1;
    }
    size_t sent = len < allowance ? len : allowance;
    assert(wire_size + sent <= sizeof(wire));
    memcpy(wire + wire_size, data, sent);
    wire_size += sent;
    return (ssize_t)sent;
}

static void flush(struct c300x_mqtt *mqtt, const struct c300x_config *config)
{
    for (int i = 0; c300x_mqtt_output_pending(&mqtt->output) > 0 && i < 10000; i++) {
        int calls = send_calls;
        c300x_mqtt_handle_poll(mqtt, config, POLLOUT, 100);
        /* Completing SUBSCRIBE can also publish availability and start date. */
        assert(send_calls - calls <= 3);
    }
    assert(c300x_mqtt_output_pending(&mqtt->output) == 0);
}

static size_t packet(size_t offset, int type, const unsigned char **payload, size_t *len)
{
    assert(offset < wire_size && wire[offset] == type);
    size_t header;
    *len = mqtt_remaining_length(wire + offset, wire_size - offset, &header);
    assert(header > 0 && offset + header + *len <= wire_size);
    *payload = wire + offset + header;
    return offset + header + *len;
}

static size_t publication(size_t offset, const char *topic, const char *body, int retain)
{
    const unsigned char *payload;
    size_t len;
    size_t next = packet(offset, retain ? 0x31 : 0x30, &payload, &len);
    size_t topic_len = strlen(topic), body_len = strlen(body);
    assert(len == topic_len + body_len + 2);
    assert(payload[0] == 0 && payload[1] == topic_len);
    assert(memcmp(payload + 2, topic, topic_len) == 0);
    assert(memcmp(payload + 2 + topic_len, body, body_len) == 0);
    return next;
}

static void setup(struct c300x_mqtt *mqtt, int *peer)
{
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    c300x_mqtt_init(mqtt);
    mqtt->fd = pair[0];
    mqtt->connect_started_at = 100;
    *peer = pair[1];
    assert(fcntl(mqtt->fd, F_SETFL, fcntl(mqtt->fd, F_GETFL) | O_NONBLOCK) == 0);
    blocked = fail_send = 0;
    allowance = sizeof(wire);
    wire_size = 0;
}

static void ack(struct c300x_mqtt *mqtt, const struct c300x_config *config, int peer)
{
    const unsigned char connack[] = {0x20, 2, 0, 0};
    assert(write(peer, connack, sizeof(connack)) == sizeof(connack));
    c300x_mqtt_handle_poll(mqtt, config, POLLIN, 200);
}

int main(void)
{
    struct c300x_config *config = calloc(1, sizeof(*config));
    struct c300x_mqtt mqtt;
    int peer;
    assert(config != NULL);
    config->mqtt_enabled = 1;
    config->mqtt_keepalive_seconds = 30;
    config->mqtt_reconnect_initial_seconds = 5;
    config->mqtt_reconnect_max_seconds = 60;
    strcpy(config->mqtt_client_id, "client");
    strcpy(config->mqtt_command_topic, "commands");
    strcpy(config->mqtt_availability_topic, "available");
    strcpy(config->mqtt_status_topic, "started");
    strcpy(config->mqtt_json_event_topic, "json");
    strcpy(config->mqtt_event_topic, "raw");

    /* CONNECT, fragmented CONNACK, then SUBSCRIBE must finish before publishes. */
    setup(&mqtt, &peer);
    mqtt.phase = MQTT_CONNECT_OUTPUT;
    allowance = 1;
    assert(mqtt_send_connect(&mqtt, config));
    c300x_mqtt_handle_poll(&mqtt, config, POLLOUT, 100);
    assert(mqtt.phase == MQTT_CONNECT_OUTPUT && !mqtt.connected);
    blocked = 1;
    int calls = send_calls;
    c300x_mqtt_handle_poll(&mqtt, config, POLLOUT, 100);
    assert(send_calls == calls + 1 && mqtt.output.offset == 1);
    assert(c300x_mqtt_poll_events(&mqtt) == (POLLOUT | POLLRDHUP));
    assert(c300x_mqtt_poll_timeout_ms(&mqtt, 100) == 500);
    blocked = 0;
    flush(&mqtt, config);
    assert(mqtt.phase == MQTT_CONNACK && !mqtt.connected);
    assert(c300x_mqtt_poll_events(&mqtt) == (POLLIN | POLLRDHUP));
    assert(c300x_mqtt_poll_timeout_ms(&mqtt, 100) == 1500);
    const unsigned char *payload;
    size_t len, offset = packet(0, 0x10, &payload, &len);
    assert(offset == wire_size && len > 10);
    assert(memcmp(payload, "\0\4MQTT\4", 7) == 0);
    assert(payload[7] == 0x26 && payload[8] == 0 && payload[9] == 30);
    const unsigned char connack[] = {0x20, 2, 0, 0};
    for (size_t i = 0; i < sizeof(connack); i++) {
        clock_ms += 1000;
        assert(write(peer, connack + i, 1) == 1);
        c300x_mqtt_handle_poll(&mqtt, config, POLLIN, 100);
        if (i < 3) {
            assert(mqtt.phase == MQTT_CONNACK);
            assert(c300x_mqtt_poll_timeout_ms(&mqtt, 100) == 1500);
        }
    }
    assert(mqtt.phase == MQTT_SUBSCRIBE_OUTPUT && !mqtt.connected && !mqtt.subscribed);
    blocked = 1;
    c300x_mqtt_publish_event(&mqtt, config, "test", "ignored", "{}");
    assert(wire_size == offset + 1);
    blocked = 0;
    flush(&mqtt, config);
    assert(mqtt.connected && mqtt.subscribed && mqtt.phase == MQTT_READY);
    offset = packet(offset, 0x82, &payload, &len);
    assert(len == 13 && payload[0] == 0 && payload[1] == 1 && payload[12] == 0);
    offset = publication(offset, "available", "online", 1);
    char date[32];
    mqtt_format_start_date(100, date, sizeof(date));
    offset = publication(offset, "started", date, 1);
    assert(offset == wire_size);
    assert(c300x_mqtt_poll_timeout_ms(&mqtt, 100) == 30000);
    assert(!(c300x_mqtt_poll_events(&mqtt) & POLLOUT));

    /* Partial event frame, queued second event and PINGREQ retain wire order. */
    allowance = 1;
    c300x_mqtt_publish_event(&mqtt, config, "test", "first", "{\"raw\":\"second\"}");
    size_t queued = c300x_mqtt_output_pending(&mqtt.output);
    assert(queued > 0);
    blocked = 1;
    c300x_mqtt_tick(&mqtt, config, 130);
    assert(mqtt.ping_remaining == queued + 2);
    for (int i = 0; i < 10; i++) {
        c300x_mqtt_tick(&mqtt, config, 130);
    }
    assert(c300x_mqtt_output_pending(&mqtt.output) == queued + 2);
    assert(c300x_mqtt_poll_timeout_ms(&mqtt, 130) == 500);
    const unsigned char command[] = {0x30, 7, 0, 1, 't', 't', 'e', 's', 't'};
    assert(write(peer, command, sizeof(command)) == sizeof(command));
    c300x_mqtt_handle_poll(&mqtt, config, POLLIN, 130);
    char received[16];
    assert(c300x_mqtt_take_command(&mqtt, received, sizeof(received)));
    assert(strcmp(received, "test") == 0);
    assert(c300x_mqtt_output_pending(&mqtt.output) == queued + 2);
    blocked = 0;
    flush(&mqtt, config);
    offset = publication(offset, "json", "first", 0);
    offset = publication(offset, "raw", "second", 0);
    offset = packet(offset, 0xc0, &payload, &len);
    assert(len == 0 && offset == wire_size && mqtt.ping_remaining == 0);
    assert(mqtt.next_ping_at == 130); /* flush helper uses wall time 100 */

    /* Saturation drops a whole new event, keeps existing bytes and ping room. */
    char big[3066];
    memset(big, 'x', sizeof(big) - 1);
    big[sizeof(big) - 1] = '\0';
    blocked = 1;
    assert(mqtt_publish(&mqtt, config, "json", big, 0, 130));
    queued = c300x_mqtt_output_pending(&mqtt.output);
    assert(queued == 3074);
    assert(!mqtt_publish(&mqtt, config, "json", "dropped", 0, 130));
    assert(mqtt.fd >= 0 && c300x_mqtt_output_pending(&mqtt.output) == queued);
    char oversized[3067];
    memset(oversized, 'x', sizeof(oversized) - 1);
    oversized[sizeof(oversized) - 1] = '\0';
    assert(!mqtt_publish(&mqtt, config, "json", oversized, 0, 130));
    assert(c300x_mqtt_output_pending(&mqtt.output) == queued);
    c300x_mqtt_tick(&mqtt, config, 130);
    assert(c300x_mqtt_output_pending(&mqtt.output) == queued + 2);
    blocked = 0;
    allowance = sizeof(wire);
    flush(&mqtt, config);
    offset = publication(offset, "json", big, 0);
    offset = packet(offset, 0xc0, &payload, &len);
    assert(offset == wire_size);

    /* A stalled or failed partial frame closes, never splices the next packet. */
    allowance = 1;
    assert(mqtt_publish(&mqtt, config, "json", "partial", 0, 130));
    blocked = 1;
    clock_ms += 499;
    c300x_mqtt_tick(&mqtt, config, 130);
    assert(mqtt.fd >= 0);
    clock_ms++;
    c300x_mqtt_tick(&mqtt, config, 130);
    assert(mqtt.fd == -1 && mqtt.next_connect_at == 135);
    assert(mqtt.output.used == 0 && mqtt.ping_remaining == 0);
    assert(c300x_mqtt_poll_events(&mqtt) == 0);
    assert(c300x_mqtt_poll_timeout_ms(&mqtt, 130) == 5000);
    close(peer);

    for (int phase = MQTT_CONNECT_OUTPUT; phase <= MQTT_READY; phase++) {
        setup(&mqtt, &peer);
        mqtt.phase = phase;
        assert(mqtt_send_packet(&mqtt, MQTT_PACKET_PINGREQ, NULL, 0));
        fail_send = 1;
        c300x_mqtt_handle_poll(&mqtt, config, POLLOUT, 200);
        assert(mqtt.fd == -1 && mqtt.next_connect_at == (phase == MQTT_READY ? 205 : 105));
        assert(mqtt.output.used == 0);
        close(peer);
    }
    setup(&mqtt, &peer);
    mqtt.phase = MQTT_CONNACK;
    mqtt.connack_deadline_ms = clock_ms + 1500;
    clock_ms += 1500;
    c300x_mqtt_tick(&mqtt, config, 200);
    assert(mqtt.fd == -1);
    close(peer);
    setup(&mqtt, &peer);
    mqtt.phase = MQTT_CONNACK;
    const unsigned char rejected[] = {0x20, 2, 0, 5};
    assert(write(peer, rejected, 4) == 4);
    c300x_mqtt_handle_poll(&mqtt, config, POLLIN, 200);
    assert(mqtt.fd == -1 && !mqtt.connected);
    close(peer);
    setup(&mqtt, &peer);
    mqtt.phase = MQTT_CONNACK;
    config->mqtt_command_topic[0] = '\0';
    ack(&mqtt, config, peer);
    assert(mqtt.connected && mqtt.subscribed);
    assert(mqtt.next_ping_at == 130);
    offset = publication(0, "available", "online", 1);
    offset = publication(offset, "started", date, 1);
    assert(offset == wire_size); /* Retained date uses attempt time 100, not ACK time 200. */
    c300x_mqtt_handle_poll(&mqtt, config, POLLHUP, 200);
    assert(mqtt.fd == -1 && mqtt.output.used == 0);
    close(peer);
    for (int phase = MQTT_CONNECT_OUTPUT; phase <= MQTT_READY; phase++) {
        setup(&mqtt, &peer);
        mqtt.phase = phase;
        mqtt.connected = phase == MQTT_READY;
        assert(mqtt_send_packet(&mqtt, MQTT_PACKET_CONNECT, NULL, 0));
        mqtt.ping_remaining = 2;
        mqtt.connack_deadline_ms = clock_ms + 1500;
        c300x_mqtt_close(&mqtt);
        assert(mqtt.fd == -1 && mqtt.phase == MQTT_CLOSED && !mqtt.connected);
        assert(mqtt.output.used == 0 && mqtt.output.offset == 0 && mqtt.output.deadline_ms == 0);
        assert(mqtt.ping_remaining == 0 && mqtt.connack_deadline_ms == 0);
        assert(c300x_mqtt_poll_events(&mqtt) == 0);
        assert(c300x_mqtt_poll_timeout_ms(&mqtt, 200) == -1);
        close(peer);
    }
    setup(&mqtt, &peer);
    memset(config->mqtt_command_topic, 't', 251);
    config->mqtt_command_topic[251] = '\0';
    assert(!mqtt_send_subscribe(&mqtt, config));
    assert(mqtt.output.used == 0);
    config->mqtt_command_topic[250] = '\0';
    assert(mqtt_send_subscribe(&mqtt, config));
    assert(mqtt.output.used == 258);
    c300x_mqtt_close(&mqtt);
    close(peer);
    setup(&mqtt, &peer);
    mqtt.phase = MQTT_READY;
    mqtt.connected = 1;
    blocked = 1;
    assert(mqtt_publish(&mqtt, config, "json", "discard-on-disable", 0, 200));
    config->mqtt_enabled = 0;
    c300x_mqtt_open_if_needed(&mqtt, config, 1, 200);
    assert(mqtt.fd == -1 && mqtt.output.used == 0);
    close(peer);
    c300x_mqtt_init(&mqtt);
    assert(c300x_mqtt_poll_timeout_ms(&mqtt, 200) == -1);
    c300x_mqtt_close(&mqtt);
    free(config);
    return 0;
}
