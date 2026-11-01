#ifndef C300X_RINGER_PROTOCOL_H
#define C300X_RINGER_PROTOCOL_H

#include "c300x_agent.h"
#include <stddef.h>

#define C300X_RINGER_VOLUME_MIN 0
#define C300X_RINGER_VOLUME_ACTIVE_MIN 0
#define C300X_RINGER_VOLUME_MAX 10
#define C300X_RINGER_VOLUME_STEP 1
#define C300X_RINGER_VOLUME_OPENWEBNET_MAX 100
#define C300X_RINGER_VOLUME_OPENWEBNET_STEP 10
#define C300X_RINGER_VOLUME_SETTLE_MS 1000

int c300x_ringer_muted_from_reply(const char *reply, int *muted);
int c300x_ringer_volume_from_reply(const char *reply, int *volume);
int c300x_ringer_volume_from_openwebnet_code(int code);
int c300x_ringer_volume_to_openwebnet_code(int volume);

int c300x_ringer_read_json(
    const struct c300x_config *config, char *body, size_t body_len,
    int *muted_out, int *volume_out, char *error, size_t error_len
);

#endif
