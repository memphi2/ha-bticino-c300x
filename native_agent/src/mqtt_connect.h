#ifndef C300X_MQTT_CONNECT_H
#define C300X_MQTT_CONNECT_H

#include <stdint.h>

/* Name resolution and TCP connect for the broker on a detached thread, so
 * a slow DNS server or dropped SYNs never hold the agent's main loop. */
struct c300x_mqtt_connect;

/* NULL when no thread could be started. */
struct c300x_mqtt_connect *c300x_mqtt_connect_start(const char *host, uint16_t port);
/* Readable once the attempt is over. */
int c300x_mqtt_connect_wake_fd(const struct c300x_mqtt_connect *attempt);
/* After the wake fd was readable: the connected nonblocking socket or -1,
 * and the attempt is freed; -2 while it is not over yet. */
int c300x_mqtt_connect_finish(struct c300x_mqtt_connect *attempt);
/* Never blocks; a running thread frees the attempt and its socket itself. */
void c300x_mqtt_connect_cancel(struct c300x_mqtt_connect *attempt);

#endif
