#ifndef C300X_VIDEO_AUDIO_SETTINGS_H
#define C300X_VIDEO_AUDIO_SETTINGS_H

#include <stdbool.h>

struct c300x_video;

bool c300x_parse_doorstation_audio_gain_request(const char *body, int *gain_tenths);
void c300x_handle_doorbell_video_audio_settings(
    int client_fd,
    struct c300x_video *video,
    const char *request_body
);

#endif
