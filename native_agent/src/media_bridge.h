#ifndef C300X_MEDIA_BRIDGE_H
#define C300X_MEDIA_BRIDGE_H

#include <stdbool.h>

#include "c300x_agent.h"

struct c300x_video;
struct c300x_video_status;

bool c300x_media_bridge_start(
    const struct c300x_config *config,
    struct c300x_video *video
);
void c300x_media_bridge_stop(struct c300x_video *video);
void c300x_media_session_stop(struct c300x_video *video);
bool c300x_media_session_warmup(struct c300x_video *video);
bool c300x_media_session_keepalive(struct c300x_video *video, bool audio);
bool c300x_media_session_renew(struct c300x_video *video);
bool c300x_media_talkback_running(const struct c300x_video *video);
void c300x_media_bridge_status(const struct c300x_video *video, struct c300x_video_status *status);

#endif
