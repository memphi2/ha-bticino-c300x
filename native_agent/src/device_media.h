#ifndef C300X_DEVICE_MEDIA_H
#define C300X_DEVICE_MEDIA_H

#include <stdbool.h>

struct c300x_config;

/* What the takeover waits for: the station's first video packet on the
 * agent's port. Returns 1 once it came, 0 when timeout_ms passed without it,
 * -1 when the start was cancelled. */
typedef int (*c300x_device_media_video_wait_fn)(void *context, int timeout_ms);

bool c300x_device_media_start(const struct c300x_config *config);
/* Adds the agent's video client to the station's stream, waits for the
 * stream on it, adds the client again while none comes, then adds the audio
 * client. True when the station accepted the video client or its stream
 * arrived. */
bool c300x_device_media_takeover(const struct c300x_config *config,
                                 c300x_device_media_video_wait_fn wait_video, void *context);
void c300x_device_media_stop(const struct c300x_config *config);

#endif
