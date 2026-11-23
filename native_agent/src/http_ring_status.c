#include "http_ring_status.h"

#include <stdio.h>

#include "http_util.h"
#include "json_util.h"
#include "media_bridge.h"
#include "openwebnet_call.h"
#include "video_rtsp.h"

void c300x_http_doorbell_call_get(int client_fd, int video_enabled, struct c300x_video *video)
{
    char body[2048];
    struct c300x_video_status video_status;
    int ring_receiver_running = 0;
    int ring_registered = 0;
    int active = 0;
    int early_media_active = 0;
    int audio_active = 0;
    int answer_requested = 0;
    int answered = 0, hangup = 0;
    int can_answer = 0;
    int can_hangup = 0;
    int talkback_ready = 0;
    int bridge_open_fds = 0;
    int bridge_active_threads = 0;
    char media_owner_json[C300X_JSON_QUOTED_LEN(32)];
    char last_error_quoted[(C300X_MAX_ERROR_LEN * 6) + 3];
    const char *last_error_json = "null";

    c300x_json_string("idle", media_owner_json, sizeof(media_owner_json));
    if (video != NULL) {
        c300x_video_status(video, &video_status);
        ring_receiver_running = video_status.ring_receiver_running;
        ring_registered = video_status.ring_registered;
        active = video_status.ring_call_active;
        early_media_active = video_status.ring_media_active;
        audio_active = video_status.ring_audio_active;
        answer_requested = video_status.ring_answer_requested;
        answered = video_status.ring_answered; hangup = video_status.ring_hangup_requested;
        can_answer = video_status.ring_call_active && !video_status.ring_answered;
        can_hangup = video_status.ring_call_active || video_status.ring_media_active;
        talkback_ready = c300x_media_ring_talkback_peer_ready(video, client_fd);
        bridge_open_fds = video_status.bridge_open_fds;
        bridge_active_threads = video_status.bridge_active_threads;
        c300x_json_string(video_status.media_owner, media_owner_json, sizeof(media_owner_json));
        last_error_json = c300x_json_string_or_null(
            video_status.last_error,
            last_error_quoted,
            sizeof(last_error_quoted)
        );
    }

    snprintf(
        body,
        sizeof(body),
        "{"
        "\"ok\":true,"
        "\"supported\":%s,"
        "\"active\":%s,"
        "\"early_media_active\":%s,"
        "\"audio_active\":%s,"
        "\"answer_requested\":%s,"
        "\"answered\":%s,\"hangup_requested\":%s,"
        "\"can_answer\":%s,"
        "\"can_hangup\":%s,"
        "\"talkback_ready\":%s,"
        "\"media_owner\":%s,"
        "\"ring_receiver_running\":%s,"
        "\"ring_registered\":%s,"
        "\"capture_supported\":false,"
        "\"open_fds\":%d,"
        "\"active_threads\":%d,"
        "\"last_error\":%s"
        "}\n",
        video_enabled ? "true" : "false",
        active ? "true" : "false",
        early_media_active ? "true" : "false",
        audio_active ? "true" : "false",
        answer_requested ? "true" : "false",
        answered ? "true" : "false", hangup ? "true" : "false",
        can_answer ? "true" : "false",
        can_hangup ? "true" : "false",
        talkback_ready ? "true" : "false",
        media_owner_json,
        ring_receiver_running ? "true" : "false",
        ring_registered ? "true" : "false",
        bridge_open_fds,
        bridge_active_threads,
        last_error_json
    );
    if (!c300x_openwebnet_deferred()) {
        c300x_http_send_json(client_fd, 200, "OK", body);
    }
}
