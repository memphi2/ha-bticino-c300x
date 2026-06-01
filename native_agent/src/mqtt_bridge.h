#ifndef C300X_MQTT_BRIDGE_H
#define C300X_MQTT_BRIDGE_H

#include "c300x_agent.h"

#include <stddef.h>
#include <time.h>

struct c300x_mqtt {
    int fd;
    int connected;
    int subscribed;
    time_t next_connect_at;
    time_t next_ping_at;
    int reconnect_delay_seconds;
    unsigned char rx_buffer[4096];
    size_t rx_len;
    char pending_command[C300X_MAX_FRAME_LEN];
    int has_pending_command;
};

void c300x_mqtt_init(struct c300x_mqtt *mqtt);
void c300x_mqtt_close(struct c300x_mqtt *mqtt);
void c300x_mqtt_reset_retry(struct c300x_mqtt *mqtt);
void c300x_mqtt_open_if_needed(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    int network_online,
    time_t now
);
int c300x_mqtt_fd(const struct c300x_mqtt *mqtt);
int c300x_mqtt_poll_timeout_ms(const struct c300x_mqtt *mqtt, time_t now);
void c300x_mqtt_handle_poll(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    short revents,
    time_t now
);
void c300x_mqtt_tick(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    time_t now
);
void c300x_mqtt_publish_event(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    const char *event_type,
    const char *event_json,
    const char *data_json
);
void c300x_mqtt_publish_raw(
    struct c300x_mqtt *mqtt,
    const struct c300x_config *config,
    const char *payload
);
int c300x_mqtt_take_command(
    struct c300x_mqtt *mqtt,
    char *out,
    size_t out_len
);

#endif
