#ifndef C300X_VIDEO_AUDIO_SETTINGS_H
#define C300X_VIDEO_AUDIO_SETTINGS_H

#include <stdbool.h>

/* {"door_level_db": 0|3|6|9|12, "fine_gain_db": -10..10}, both whole numbers. */
bool c300x_parse_audio_level_request(const char *body, int *door_level_db, int *fine_gain_db);
bool c300x_try_handle_doorbell_video_audio_settings_route(
    int client_fd,
    const char *method,
    const char *path,
    const char *request_body
);

#endif
