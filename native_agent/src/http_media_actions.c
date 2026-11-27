#include "http_media_actions.h"

#include <stdio.h>
#include <string.h>

#include "http_util.h"
#include "json_util.h"
#include "video_rtsp.h"

/* Zero: the handler returns; the request runs again or was answered here. */
static int ran(int client_fd, struct c300x_video_control *control, struct c300x_video *video,
               enum c300x_video_control_op op, int argument, const char *where, int *result)
{
    const char *error = "";
    char body[96];
    enum c300x_video_control_state state = c300x_video_control_run(control, video, op, argument, where, result,
                                                                   &error);

    if (state == C300X_VIDEO_CONTROL_REFUSED) {
        snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"%s\"}\n", error);
        c300x_http_send_json(client_fd, 503, "Service Unavailable", body);
    }
    return state == C300X_VIDEO_CONTROL_DONE;
}

void c300x_http_doorbell_video_activate(
    int client_fd,
    struct c300x_video_control *control, struct c300x_video *video,
    const struct request *request, const char *devaddr
)
{
    int audio = 1;
    int done;
    char body[2048];
    char last_error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];
    struct c300x_video_status status;

    if (video == NULL) {
        c300x_http_send_json(client_fd, 503, "Service Unavailable", "{\"ok\":false,\"error\":\"video_unavailable\"}\n");
        return;
    }
    (void)c300x_json_bool_field(request->body, "audio", &audio);
    c300x_video_status(video, &status);
    if (status.ring_call_active || status.ring_media_active) {
        snprintf(body, sizeof(body), "{\"ok\":true,\"audio\":%s,\"ring_active\":true,\"media_owner\":\"ring\"}\n",
                 audio ? "true" : "false");
        c300x_http_send_json(client_fd, 200, "OK", body);
        return;
    }
    if (!ran(client_fd, control, video, C300X_VIDEO_CONTROL_ACTIVATE, audio, devaddr, &done)) {
        return;
    }
    if (!done) {
        c300x_video_status(video, &status);
        const char *error = status.last_error[0] != '\0' ? status.last_error : "unknown";
        int conflict = strcmp(error, "external_session_active") == 0;
        snprintf(body, sizeof(body),
                 "{\"ok\":false,\"error\":\"%s\",\"last_error\":%s,\"external_media_active\":%s}\n",
                 conflict ? "external_session_active" : "video_activate_failed",
                 c300x_json_string(error, last_error_json, sizeof(last_error_json)),
                 status.external_media_active ? "true" : "false");
        c300x_http_send_json(client_fd, conflict ? 409 : 503, conflict ? "Conflict" : "Service Unavailable", body);
        return;
    }
    snprintf(body, sizeof(body), "{\"ok\":true,\"audio\":%s}\n", audio ? "true" : "false");
    c300x_http_send_json(client_fd, 200, "OK", body);
}

void c300x_http_doorbell_video_stop(int client_fd, struct c300x_video_control *control, struct c300x_video *video)
{
    int done;

    if (video != NULL && !ran(client_fd, control, video, C300X_VIDEO_CONTROL_STOP, 0, NULL, &done)) {
        return;
    }
    c300x_http_send_json(client_fd, 200, "OK", "{\"ok\":true}\n");
}

int c300x_http_doorbell_call_answer(
    int client_fd,
    struct c300x_video_control *control, struct c300x_video *video,
    const struct request *request
)
{
    struct c300x_video_status video_status;
    char body[1024];
    int done;

    (void)request;
    if (video == NULL) {
        c300x_http_send_json(client_fd, 503, "Service Unavailable", "{\"ok\":false,\"error\":\"video_unavailable\"}\n");
        return 0;
    }
    if (!ran(client_fd, control, video, C300X_VIDEO_CONTROL_ANSWER, 0, NULL, &done)) {
        return 0;
    }
    if (!done) {
        c300x_video_status(video, &video_status);
        snprintf(
            body,
            sizeof(body),
            "{\"ok\":false,\"error\":\"ring_call_not_active\",\"ring_call_active\":%s,\"ring_media_active\":%s,\"answered\":%s}\n",
            video_status.ring_call_active ? "true" : "false",
            video_status.ring_media_active ? "true" : "false",
            video_status.ring_answered ? "true" : "false"
        );
        c300x_http_send_json(client_fd, 409, "Conflict", body);
        return 0;
    }
    c300x_video_status(video, &video_status);
    snprintf(body, sizeof(body),
        "{\"ok\":true,\"audio\":true,\"answer_requested\":%s,\"answered\":%s,\"media_owner\":\"ring\"}\n",
        video_status.ring_answer_requested ? "true" : "false", video_status.ring_answered ? "true" : "false");
    c300x_http_send_json(client_fd, 200, "OK", body);
    return 1;
}

int c300x_http_doorbell_call_hangup(int client_fd, struct c300x_video_control *control, struct c300x_video *video)
{
    int done;

    if (video != NULL && !ran(client_fd, control, video, C300X_VIDEO_CONTROL_HANGUP, 0, NULL, &done)) {
        return 0;
    }
    c300x_http_send_json(client_fd, 200, "OK", "{\"ok\":true}\n");
    return 1;
}

void c300x_http_home_call_start(
    int client_fd,
    struct c300x_video_control *control, struct c300x_video *video,
    const struct request *request
) {
    int duration_seconds = 0;
    int done;
    char body[2048];
    char last_error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];

    if (request != NULL) {
        (void)c300x_json_int_field(request->body, "duration_seconds", &duration_seconds);
    }
    if (duration_seconds < 0 || duration_seconds > C300X_HOME_CALL_MAX_DURATION_SECONDS) {
        c300x_http_send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_duration_seconds\"}\n");
        return;
    }
    if (video == NULL) {
        c300x_http_send_json(client_fd, 503, "Service Unavailable", "{\"ok\":false,\"error\":\"video_unavailable\"}\n");
        return;
    }
    if (!ran(client_fd, control, video, C300X_VIDEO_CONTROL_HOME_START, duration_seconds, NULL, &done)) {
        return;
    }
    if (!done) {
        struct c300x_video_status status;
        int http_status;
        const char *http_text;
        const char *error;

        c300x_video_status(video, &status);
        error = status.last_error[0] != '\0' ? status.last_error : "unknown";
        http_status = (
            strcmp(error, "external_session_active") == 0
            || strcmp(error, "home_call_active") == 0
            || strcmp(error, "media_session_active") == 0
        ) ? 409 : 503;
        http_text = http_status == 409 ? "Conflict" : "Service Unavailable";
        c300x_json_string(error, last_error_json, sizeof(last_error_json));
        snprintf(
            body,
            sizeof(body),
            "{\"ok\":false,\"error\":\"home_call_start_failed\",\"last_error\":%s}\n",
            last_error_json
        );
        c300x_http_send_json(client_fd, http_status, http_text, body);
        return;
    }
    snprintf(body, sizeof(body), "{\"ok\":true,\"duration_seconds\":%d}\n", duration_seconds);
    c300x_http_send_json(client_fd, 200, "OK", body);
}

void c300x_http_home_call_stop(int client_fd, struct c300x_video_control *control, struct c300x_video *video)
{
    int done;

    if (video != NULL && !ran(client_fd, control, video, C300X_VIDEO_CONTROL_HOME_STOP, 0, NULL, &done)) {
        return;
    }
    c300x_http_send_json(client_fd, 200, "OK", "{\"ok\":true}\n");
}
