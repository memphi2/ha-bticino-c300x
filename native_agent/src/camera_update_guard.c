#include "camera_update_guard.h"
#include "video_rtsp.h"

int c300x_camera_update_media_busy(struct c300x_video *video)
{
    struct c300x_video_status status;
    c300x_video_status(video, &status);
    return status.call_active || status.clients || status.media_starting
        || status.bridge_media_active || status.bridge_stop_in_progress
        || status.external_media_active || status.ring_call_active
        || status.ring_media_active || status.ring_audio_active
        || status.home_call_active || status.home_call_running
        || status.ring_answer_requested || status.talkback_running;
}
