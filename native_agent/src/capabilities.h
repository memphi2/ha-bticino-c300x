#ifndef C300X_CAPABILITIES_H
#define C300X_CAPABILITIES_H

#include "c300x_agent.h"

struct c300x_capabilities_context {
    const char *device_id;
    const char *device_firmware;
    const char *bundle_hash;
    int maintenance_supported;
    int activations_count;
    int device_codec_pcmu;
    int ringer_min_volume;
    int ringer_max_volume;
    int ringer_volume_step;
};

/* Serialize an already resolved runtime snapshot without device or network I/O. */
int c300x_capabilities_json(
    const struct c300x_config *config,
    const struct c300x_capabilities_context *context,
    char *body,
    size_t body_len
);

#endif
