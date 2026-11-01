#include "ringer_protocol.h"
#include "json_util.h"

#include <stdio.h>
#include <string.h>

int c300x_ringer_muted_from_reply(const char *reply, int *muted)
{
    if (reply == NULL || muted == NULL) {
        return 0;
    }
    if (strcmp(reply, "*#8**33*0##") == 0 || strcmp(reply, "*#8**#33*0##") == 0) {
        *muted = 1;
        return 1;
    }
    if (strcmp(reply, "*#8**33*1##") == 0 || strcmp(reply, "*#8**#33*1##") == 0) {
        *muted = 0;
        return 1;
    }
    return 0;
}

int c300x_ringer_volume_from_reply(const char *reply, int *volume)
{
    int value;
    int consumed = 0;

    if (reply == NULL || volume == NULL) {
        return 0;
    }
    if (
        (
            sscanf(reply, "*#8**41*%d##%n", &value, &consumed) == 1
            || sscanf(reply, "*#8**#41*%d##%n", &value, &consumed) == 1
        )
        && consumed > 0
        && reply[consumed] == '\0'
        && value >= C300X_RINGER_VOLUME_MIN
        && value <= C300X_RINGER_VOLUME_OPENWEBNET_MAX
        && value % C300X_RINGER_VOLUME_OPENWEBNET_STEP == 0
    ) {
        *volume = c300x_ringer_volume_from_openwebnet_code(value);
        return 1;
    }
    return 0;
}

int c300x_ringer_volume_from_openwebnet_code(int code)
{
    return code / C300X_RINGER_VOLUME_OPENWEBNET_STEP;
}

int c300x_ringer_volume_to_openwebnet_code(int volume)
{
    return volume * C300X_RINGER_VOLUME_OPENWEBNET_STEP;
}

int c300x_ringer_read_json(
    const struct c300x_config *config, char *body, size_t body_len,
    int *muted_out, int *volume_out, char *error, size_t error_len
)
{
    char muted_reply[C300X_MAX_FRAME_LEN];
    char volume_reply[C300X_MAX_FRAME_LEN];
    char muted_reply_json[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN)];
    char volume_reply_json[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN)];
    char muted_json[8];
    char volume_json[16];
    char muted_status_part[32];
    char volume_status_part[40];
    char volume_raw_part[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN) + 32];
    int muted;
    int volume;

    *muted_out = -1;
    *volume_out = -1;
    muted_status_part[0] = '\0';
    volume_status_part[0] = '\0';
    volume_raw_part[0] = '\0';

    if (!c300x_openwebnet_send(config, "*#8**33##", muted_reply, sizeof(muted_reply), error, error_len)) {
        return 0;
    }
    c300x_json_string(muted_reply, muted_reply_json, sizeof(muted_reply_json));
    if (c300x_ringer_muted_from_reply(muted_reply, &muted)) {
        *muted_out = muted;
        snprintf(muted_json, sizeof(muted_json), "%s", muted ? "true" : "false");
    } else {
        snprintf(muted_json, sizeof(muted_json), "null");
        snprintf(muted_status_part, sizeof(muted_status_part), ",\"status\":\"unknown\"");
    }

    if (c300x_openwebnet_send(config, "*#8**41##", volume_reply, sizeof(volume_reply), error, error_len)) {
        c300x_json_string(volume_reply, volume_reply_json, sizeof(volume_reply_json));
        snprintf(volume_raw_part, sizeof(volume_raw_part), ",\"volume_raw\":%s", volume_reply_json);
        if (c300x_ringer_volume_from_reply(volume_reply, &volume)) {
            *volume_out = volume;
            snprintf(volume_json, sizeof(volume_json), "%d", volume);
        } else {
            snprintf(volume_json, sizeof(volume_json), "null");
            snprintf(volume_status_part, sizeof(volume_status_part), ",\"volume_status\":\"unknown\"");
        }
    } else {
        snprintf(volume_json, sizeof(volume_json), "null");
        snprintf(volume_status_part, sizeof(volume_status_part), ",\"volume_status\":\"unknown\"");
    }

    int written = snprintf(
        body,
        body_len,
        "{\"ok\":true,\"muted\":%s,\"volume\":%s%s%s,\"raw\":%s%s}\n",
        muted_json,
        volume_json,
        muted_status_part,
        volume_status_part,
        muted_reply_json,
        volume_raw_part
    );
    if (written < 0 || (size_t)written >= body_len) {
        snprintf(error, error_len, "%s", "ringer_response_too_large");
        return 0;
    }
    return 1;
}
