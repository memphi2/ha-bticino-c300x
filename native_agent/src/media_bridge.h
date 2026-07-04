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
bool c300x_media_ring_receiver_start(
    const struct c300x_config *config,
    struct c300x_video *video
);
void c300x_media_ring_receiver_stop(struct c300x_video *video);
bool c300x_media_home_call_start(
    const struct c300x_config *config,
    struct c300x_video *video,
    int duration_seconds
);
void c300x_media_home_call_stop(struct c300x_video *video);
void c300x_media_session_stop(struct c300x_video *video);
bool c300x_media_session_stop_in_progress(const struct c300x_video *video);
bool c300x_media_session_keepalive(struct c300x_video *video, bool audio);
bool c300x_media_ring_call_answer(struct c300x_video *video);
void c300x_media_ring_call_hangup(struct c300x_video *video);
void c300x_media_bridge_set_doorstation_audio_gain_tenths(
    struct c300x_video *video,
    int gain_tenths
);
bool c300x_media_talkback_running(const struct c300x_video *video);
bool c300x_media_ring_call_active(const struct c300x_video *video);
void c300x_media_bridge_status(const struct c300x_video *video, struct c300x_video_status *status);

#endif
