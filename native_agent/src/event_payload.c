#include "event_payload.h"

#include "string_util.h"

#include <stdio.h>
#include <string.h>

#define C300X_EVENT_PATH_JSON_LEN ((C300X_MAX_PATH_LEN * 6) + 1)
#define C300X_EVENT_JSON_QUOTED_LEN(value_len) (((value_len) * 6) + 3)

static size_t event_json_escape_string(const char *value, char *out, size_t out_len)
{
    size_t used = 0;

    if (out_len == 0) {
        return 0;
    }
    for (const unsigned char *cursor = (const unsigned char *)(value != NULL ? value : ""); *cursor != '\0'; cursor++) {
        const char *escape = NULL;
        switch (*cursor) {
            case '"':
                escape = "\\\"";
                break;
            case '\\':
                escape = "\\\\";
                break;
            case '\b':
                escape = "\\b";
                break;
            case '\f':
                escape = "\\f";
                break;
            case '\n':
                escape = "\\n";
                break;
            case '\r':
                escape = "\\r";
                break;
            case '\t':
                escape = "\\t";
                break;
            default:
                break;
        }
        if (escape != NULL) {
            if (!c300x_appendf(out, out_len, &used, "%s", escape)) {
                return used;
            }
        } else if (*cursor < 0x20) {
            if (!c300x_appendf(out, out_len, &used, "\\u%04x", *cursor)) {
                return used;
            }
        } else if (used + 1 < out_len) {
            out[used++] = (char)*cursor;
            out[used] = '\0';
        } else {
            return used;
        }
    }
    out[used] = '\0';
    return used;
}

static const char *event_json_string(const char *value, char *out, size_t out_len)
{
    size_t used;

    if (out == NULL || out_len < 3) {
        return "\"\"";
    }
    out[0] = '"';
    used = event_json_escape_string(value != NULL ? value : "", out + 1, out_len - 2);
    if (used + 2 >= out_len) {
        out[out_len - 2] = '"';
        out[out_len - 1] = '\0';
    } else {
        out[used + 1] = '"';
        out[used + 2] = '\0';
    }
    return out;
}

int c300x_event_payload_needs_doorbell_state(const char *event_type)
{
    return event_type != NULL && (
        strcmp(event_type, "doorbell.pressed") == 0
        || strcmp(event_type, "doorbell.view_requested") == 0
        || strcmp(event_type, "doorbell.media.closed") == 0
    );
}

static const char *doorbell_state_for_event(const char *event_type)
{
    if (event_type == NULL) {
        return "idle";
    }
    if (strcmp(event_type, "doorbell.pressed") == 0) {
        return "ringing";
    }
    if (strcmp(event_type, "doorbell.view_requested") == 0) {
        return "view_requested";
    }
    return "idle";
}

static int build_doorbell_event_video_json(
    const struct c300x_config *config,
    struct c300x_video *video,
    const char *event_type,
    char *out,
    size_t out_len
)
{
    struct c300x_video_status status;
    char stream_path[C300X_EVENT_PATH_JSON_LEN];
    char audio_stream_path[C300X_EVENT_PATH_JSON_LEN];
    char recorder_stream_path[C300X_EVENT_PATH_JSON_LEN];
    char media_owner_json[C300X_EVENT_JSON_QUOTED_LEN(32)];
    char external_owner_json[C300X_EVENT_JSON_QUOTED_LEN(32)];
    int available;
    int window_available;
    int external_media_active;
    int ring_event_pending;
    int ring_owner;
    int unanswered_ring_call;
    int written;

    if (config == NULL || video == NULL || out == NULL) {
        return 0;
    }
    c300x_video_status(video, &status);
    ring_event_pending = (
        event_type != NULL
        && strcmp(event_type, "doorbell.pressed") == 0
        && status.ring_receiver_running
        && status.ring_registered
        && !status.home_call_running
        && !status.home_call_active
        && !status.external_media_active
    );
    ring_owner = status.ring_call_active || status.ring_media_active || ring_event_pending;
    unanswered_ring_call = ring_owner && !status.ring_answer_requested && !status.ring_answered;
    available = (
        !status.home_call_running
        && !status.home_call_active
        && (
            ring_event_pending
            || status.ring_call_active
            || status.ring_media_active
            || status.bridge_media_active
            || status.call_active
        )
    );
    window_available = config->video_enabled && available;
    external_media_active = status.external_media_active && !available;
    event_json_escape_string(config->video_rtsp_video_path, stream_path, sizeof(stream_path));
    event_json_escape_string(config->video_rtsp_path, audio_stream_path, sizeof(audio_stream_path));
    event_json_escape_string(config->video_rtsp_recorder_path, recorder_stream_path, sizeof(recorder_stream_path));
    event_json_string(ring_owner ? "ring" : status.media_owner, media_owner_json, sizeof(media_owner_json));
    event_json_string(status.external_owner, external_owner_json, sizeof(external_owner_json));
    written = snprintf(
        out,
        out_len,
        "{"
        "\"available\":%s,"
        "\"window_available\":%s,"
        "\"stream_path\":\"%s\","
        "\"audio_stream_path\":\"%s\","
        "\"recorder_stream_path\":\"%s\","
        "\"media_owner\":%s,"
        "\"external_media_active\":%s,"
        "\"bridge\":{"
        "\"media_owner\":%s,"
        "\"external_media_active\":%s,"
        "\"external_owner\":%s,"
        "\"ring_receiver_running\":%s,"
        "\"ring_registered\":%s,"
        "\"ring_call_active\":%s,"
        "\"ring_media_active\":%s,"
        "\"ring_audio_active\":%s,"
        "\"ring_answer_requested\":%s,"
        "\"ring_answered\":%s,"
        "\"ring_hangup_requested\":%s,"
        "\"unanswered_ring_call\":%s,"
        "\"clients\":%d,"
        "\"max_clients\":%d,"
        "\"ring_preview_sharing\":%s"
        "}"
        "}",
        (config->video_enabled && available && !external_media_active) ? "true" : "false",
        window_available ? "true" : "false",
        stream_path,
        audio_stream_path,
        recorder_stream_path,
        media_owner_json,
        external_media_active ? "true" : "false",
        media_owner_json,
        external_media_active ? "true" : "false",
        external_owner_json,
        status.ring_receiver_running ? "true" : "false",
        status.ring_registered ? "true" : "false",
        status.ring_call_active ? "true" : "false",
        status.ring_media_active ? "true" : "false",
        status.ring_audio_active ? "true" : "false",
        status.ring_answer_requested ? "true" : "false",
        status.ring_answered ? "true" : "false",
        status.ring_hangup_requested ? "true" : "false",
        unanswered_ring_call ? "true" : "false",
        status.clients,
        status.max_clients > 0 ? status.max_clients : 1,
        status.max_clients > 1 ? "true" : "false"
    );
    return written >= 0 && (size_t)written < out_len;
}

int c300x_event_payload_build_doorbell_state(
    const struct c300x_config *config,
    struct c300x_video *video,
    const char *event_type,
    char *out,
    size_t out_len
)
{
    char doorbell_state_json[32];
    char video_json[2048];
    int has_video;
    int written;

    if (out == NULL || out_len == 0) {
        return 0;
    }
    event_json_string(
        doorbell_state_for_event(event_type),
        doorbell_state_json,
        sizeof(doorbell_state_json)
    );
    has_video = video != NULL
        && build_doorbell_event_video_json(config, video, event_type, video_json, sizeof(video_json));
    written = has_video
        ? snprintf(out, out_len, "\"doorbell\":%s,\"video\":%s", doorbell_state_json, video_json)
        : snprintf(out, out_len, "\"doorbell\":%s", doorbell_state_json);
    return written >= 0 && (size_t)written < out_len;
}

void c300x_event_payload_build_data_json(
    const struct c300x_config *config,
    struct c300x_video *video,
    const char *event_type,
    const char *data_json,
    char *out,
    size_t out_len
) {
    char doorbell_json[2304];
    const char *source = data_json != NULL ? data_json : "{}";
    size_t source_len;
    size_t used = 0;

    if (
        !c300x_event_payload_needs_doorbell_state(event_type)
        || !c300x_event_payload_build_doorbell_state(
            config,
            video,
            event_type,
            doorbell_json,
            sizeof(doorbell_json)
        )
    ) {
        c300x_copy_string(out, out_len, source);
        return;
    }
    source_len = strlen(source);
    if (source_len < 2 || source[0] != '{' || source[source_len - 1] != '}') {
        c300x_copy_string(out, out_len, source);
        return;
    }
    if (!c300x_appendf(
        out,
        out_len,
        &used,
        "%.*s%s%s}",
        (int)(source_len - 1),
        source,
        source_len == 2 ? "" : ",",
        doorbell_json
    )) {
        c300x_copy_string(out, out_len, source);
    }
}
