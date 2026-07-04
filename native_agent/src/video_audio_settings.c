#include "video_audio_settings.h"

#include "http_util.h"
#include "media_audio.h"
#include "video_rtsp.h"

#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>

#define C300X_DOORSTATION_AUDIO_GAIN_FIELD "\"doorstation_audio_gain_tenths\""

static bool json_value_terminates(char ch)
{
    return ch == '\0' || ch == ',' || ch == '}' || ch == ']';
}

static bool parse_json_int_field(const char *body, const char *field_pattern, int *out)
{
    const char *found;
    const char *ptr;
    char *end = NULL;
    long value;

    if (body == NULL || out == NULL) {
        return false;
    }
    found = strstr(body, field_pattern);
    if (found == NULL) {
        return false;
    }
    ptr = strchr(found + strlen(field_pattern), ':');
    if (ptr == NULL) {
        return false;
    }
    ptr++;
    while (*ptr != '\0' && isspace((unsigned char)*ptr)) {
        ptr++;
    }
    errno = 0;
    value = strtol(ptr, &end, 10);
    if (errno != 0 || end == ptr || value < INT_MIN || value > INT_MAX) {
        return false;
    }
    while (*end != '\0' && isspace((unsigned char)*end)) {
        end++;
    }
    if (!json_value_terminates(*end)) {
        return false;
    }
    *out = (int)value;
    return true;
}

bool c300x_parse_doorstation_audio_gain_request(const char *body, int *gain_tenths)
{
    int parsed_gain_tenths;

    if (!parse_json_int_field(
            body,
            C300X_DOORSTATION_AUDIO_GAIN_FIELD,
            &parsed_gain_tenths
        )
    ) {
        return false;
    }
    if (
        parsed_gain_tenths < C300X_DOORSTATION_AUDIO_GAIN_MIN_TENTHS
        || parsed_gain_tenths > C300X_DOORSTATION_AUDIO_GAIN_MAX_TENTHS
        || parsed_gain_tenths % C300X_DOORSTATION_AUDIO_GAIN_STEP_TENTHS != 0
    ) {
        return false;
    }
    *gain_tenths = parsed_gain_tenths;
    return true;
}

void c300x_handle_doorbell_video_audio_settings(
    int client_fd,
    struct c300x_video *video,
    const char *request_body
)
{
    int gain_tenths;

    if (video == NULL) {
        c300x_http_send_json(
            client_fd,
            503,
            "Service Unavailable",
            "{\"ok\":false,\"error\":\"video_unavailable\"}\n"
        );
        return;
    }
    if (!c300x_parse_doorstation_audio_gain_request(request_body, &gain_tenths)) {
        c300x_http_send_json(
            client_fd,
            400,
            "Bad Request",
            "{\"ok\":false,\"error\":\"invalid_audio_gain\"}\n"
        );
        return;
    }
    c300x_video_set_doorstation_audio_gain_tenths(video, gain_tenths);
    c300x_http_send_json(client_fd, 200, "OK", "{\"ok\":true}\n");
}
