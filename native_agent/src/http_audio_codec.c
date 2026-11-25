#include "http_audio_codec.h"
#include "audio_codec.h"
#include "http_util.h"
#include "json_util.h"
#include "string_util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct codec_reply {
    struct c300x_audio_codec_status status;
    char running_state[C300X_AUDIO_CODEC_STATE_LEN];
};

static void reply_codec(int fd, int rebooting, void *context)
{
    struct codec_reply *reply = context;
    char body[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN) + 256];
    c300x_audio_codec_action_body(&reply->status, reply->running_state, rebooting, body, sizeof(body));
    c300x_http_send_json(fd, 200, "OK", body);
}

int c300x_http_audio_codec_route(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, const char *running_state,
    const struct request *request, c300x_schedule_command_fn schedule)
{
    const char *action = NULL, *confirmation = NULL;
    if (strcmp(request->method, "GET") == 0
        && strcmp(request->path, "/api/v1/maintenance/audio-codec") == 0) {
        action = "status";
    } else if (strcmp(request->method, "POST") == 0) {
        if (strcmp(request->path, "/api/v1/maintenance/audio-codec/actions/apply") == 0) {
            action = "apply";
            confirmation = "apply_audio_codec_patch";
        } else if (strcmp(request->path, "/api/v1/maintenance/audio-codec/actions/restore") == 0) {
            action = "restore";
            confirmation = "restore_audio_codec_patch";
        }
    }
    if (action == NULL) {
        return 0;
    }
    if (!maintenance_authorized(config, request)) {
        c300x_http_send_json(fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return 1;
    }
    if (confirmation == NULL) {
        struct c300x_audio_codec_status status;
        char body[512];
        (void)c300x_audio_codec_read_status(&status);
        c300x_audio_codec_status_body(&status, running_state, body, sizeof(body));
        c300x_http_send_json(fd, 200, "OK", body);
        return 1;
    }
    if (!confirm_matches(request, confirmation)) {
        c300x_http_send_json(fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return 1;
    }
    struct codec_reply *reply = calloc(1, sizeof(*reply));
    if (reply == NULL) {
        c300x_http_send_json(fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        return 1;
    }
    char error[C300X_MAX_ERROR_LEN] = "";
    c300x_copy_string(reply->running_state, sizeof(reply->running_state), running_state);
    /* File/remount transaction stays together; only its reboot tail is async. */
    int ok = strcmp(action, "apply") == 0
        ? c300x_audio_codec_apply(&reply->status, error, sizeof(error))
        : c300x_audio_codec_restore(&reply->status, error, sizeof(error));
    if (!ok) {
        char error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];
        char body[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN) + 256];
        c300x_json_string(error, error_json, sizeof(error_json));
        snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"audio_codec_%s_failed\",\"detail\":%s}\n",
            action, error_json);
        int blocked = strcmp(error, C300X_AUDIO_CODEC_TEST_BUILD_BLOCKED) == 0
            || strcmp(error, C300X_AUDIO_CODEC_RECOVERY_BLOCKED) == 0;
        c300x_http_send_json(fd, blocked ? 403 : 500, blocked ? "Forbidden" : "Internal Server Error", body);
        free(reply);
        return 1;
    }
    if (reply->status.changed) {
        owner->record_write(owner->write_context, "audio_codec", action);
    }
    int reboot_requested = 1;
    (void)c300x_json_bool_field(request->body, "reboot", &reboot_requested);
    if (reboot_requested && config->maintenance_reboot_enabled
        && c300x_audio_codec_reboot_required(&reply->status, running_state)) {
        c300x_http_service_reboot(owner, fd, config, schedule, reply_codec, reply, free);
    } else {
        reply_codec(fd, 0, reply);
        free(reply);
    }
    return 1;
}
