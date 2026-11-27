#include "video_audio_settings.h"

#include "audio_level.h"
#include "http_util.h"
#include "json_util.h"

#include <stdio.h>
#include <string.h>

#define C300X_DOORSTATION_AUDIO_SETTINGS_PATH "/api/v1/video/doorbell/audio"

bool c300x_parse_audio_level_request(const char *body, int *door_level_db, int *fine_gain_db)
{
    int door;
    int fine;

    if (body == NULL || !c300x_json_object_valid(body)
        || c300x_json_int_field_checked(body, "door_level_db", &door) != 1
        || c300x_json_int_field_checked(body, "fine_gain_db", &fine) != 1
        || !c300x_audio_level_valid(door, fine)) {
        return false;
    }
    *door_level_db = door;
    *fine_gain_db = fine;
    return true;
}

static void handle_audio_settings(int client_fd, const char *request_body)
{
    char level[C300X_AUDIO_LEVEL_JSON_MAX];
    char response[C300X_AUDIO_LEVEL_JSON_MAX + 48];
    int door;
    int fine;

    if (!c300x_parse_audio_level_request(request_body, &door, &fine) || !c300x_audio_level_set(door, fine)) {
        c300x_http_send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_audio_level\"}\n");
        return;
    }
    if (c300x_audio_level_json(level, sizeof(level)) == 0) {
        snprintf(level, sizeof(level), "null");
    }
    snprintf(response, sizeof(response), "{\"ok\":true,\"audio_level\":%s}\n", level);
    c300x_http_send_json(client_fd, 200, "OK", response);
}

bool c300x_try_handle_doorbell_video_audio_settings_route(
    int client_fd,
    const char *method,
    const char *path,
    const char *request_body
)
{
    if (strcmp(method, "POST") != 0 || strcmp(path, C300X_DOORSTATION_AUDIO_SETTINGS_PATH) != 0) {
        return false;
    }
    handle_audio_settings(client_fd, request_body);
    return true;
}
