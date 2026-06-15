#ifndef C300X_DEVICE_ROUTING_H
#define C300X_DEVICE_ROUTING_H

#include <stddef.h>

#include "c300x_agent.h"

#define C300X_DEVICE_ROUTING_STATE_LEN 32
#define C300X_DEVICE_ROUTING_HASH_LEN 65
#define C300X_DEVICE_ROUTING_ERROR_LEN C300X_MAX_ERROR_LEN

struct c300x_device_routing_status {
    int supported;
    int patched;
    int backup_present;
    char state[C300X_DEVICE_ROUTING_STATE_LEN];
    char file_sha256[C300X_DEVICE_ROUTING_HASH_LEN];
    char backup_sha256[C300X_DEVICE_ROUTING_HASH_LEN];
    char error[C300X_DEVICE_ROUTING_ERROR_LEN];
};

int c300x_device_routing_read_status(
    struct c300x_device_routing_status *status
);
int c300x_device_routing_apply(
    struct c300x_device_routing_status *status,
    char *error,
    size_t error_len
);
int c300x_device_routing_restore(
    struct c300x_device_routing_status *status,
    char *error,
    size_t error_len
);

#endif
