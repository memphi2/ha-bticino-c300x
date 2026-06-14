#ifndef C300X_EVENT_PAYLOAD_H
#define C300X_EVENT_PAYLOAD_H

#include <stddef.h>

#include "c300x_agent.h"
#include "video_rtsp.h"

int c300x_event_payload_needs_doorbell_state(const char *event_type);
int c300x_event_payload_build_doorbell_state(
    const struct c300x_config *config,
    struct c300x_video *video,
    const char *event_type,
    char *out,
    size_t out_len
);

#endif
