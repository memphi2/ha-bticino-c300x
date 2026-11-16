#ifndef C300X_MQTT_OUTPUT_H
#define C300X_MQTT_OUTPUT_H

#include <stddef.h>

/* One maximum legacy payload plus its maximum fixed header. No heap queue. */
#define C300X_MQTT_OUTPUT_CAPACITY (3072 + 5)
#define C300X_MQTT_WRITE_TIMEOUT_MS 500

struct c300x_mqtt_output {
    unsigned char bytes[C300X_MQTT_OUTPUT_CAPACITY];
    size_t used;
    size_t offset;
    long long deadline_ms;
};

size_t c300x_mqtt_output_pending(const struct c300x_mqtt_output *output);
/* Atomic admission: rejection never appends a partial packet. Publications
 * leave two bytes for the single outstanding PINGREQ control frame. */
int c300x_mqtt_output_enqueue(struct c300x_mqtt_output *output, unsigned char type,
    const unsigned char *payload, size_t size, long long now);
/* One nonblocking send per call; bytes sent, zero on backpressure, -1 on error.
 * The owner closes the connection on error/expiry, never skips a partial frame. */
int c300x_mqtt_output_flush(struct c300x_mqtt_output *output, int fd, long long now);
int c300x_mqtt_output_timeout(const struct c300x_mqtt_output *output, long long now);

#endif
