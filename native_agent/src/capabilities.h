#ifndef C300X_CAPABILITIES_H
#define C300X_CAPABILITIES_H

#include "c300x_agent.h"

struct c300x_capabilities_context {
    const char *device_id;
    const char *device_model;
    const char *display_kind;
    /* ok, unread or mismatch: c300x_device_model_check_name(). */
    const char *model_check;
    const char *board;
    const char *article;
    const char *device_firmware;
    const char *bundle_hash;
    int maintenance_supported;
    int memo_led_present;
    int ipv6_firewall_hook;
    int picture_supported;
    int activations_count;
    int device_codec_pcmu;
    int camera_resolution_fixed;
    /* Key beep, alerts, bridge, ringer mute: c300x_device_display_features(). */
    int display_features;
    int announcements_supported;
    int https_callbacks;
    int https_callbacks_enabled;
    int ringer_min_volume;
    int ringer_max_volume;
    int ringer_volume_step;
    /* C100X only: ,"c100x_display":{...}; NULL elsewhere. */
    const char *c100x;
};

/* Serialize an already resolved runtime snapshot without device or network I/O. */
int c300x_capabilities_json(
    const struct c300x_config *config,
    const struct c300x_capabilities_context *context,
    char *body,
    size_t body_len
);

#endif
