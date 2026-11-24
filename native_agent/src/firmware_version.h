#ifndef C300X_FIRMWARE_VERSION_H
#define C300X_FIRMWARE_VERSION_H

#include "c300x_agent.h"

void resolve_device_firmware(
    const struct c300x_config *config,
    char *out,
    size_t out_len
);

#endif
