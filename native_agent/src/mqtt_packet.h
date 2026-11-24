#ifndef C300X_MQTT_PACKET_H
#define C300X_MQTT_PACKET_H

#include "c300x_agent.h"

#include <stddef.h>

/* MQTT 3.1.1 payloads, built without any connection state. A size of 0
 * means the configured values do not fit. */
size_t c300x_mqtt_write_utf8(unsigned char *out, size_t out_len, const char *value);
size_t c300x_mqtt_connect_payload(const struct c300x_config *config, unsigned char *payload, size_t payload_len);
size_t c300x_mqtt_subscribe_payload(const struct c300x_config *config, unsigned char *payload, size_t payload_len);
/* The "raw" string of an event's data JSON; 0 when there is none. */
int c300x_mqtt_json_raw_field(const char *data_json, char *out, size_t out_len);

#endif
