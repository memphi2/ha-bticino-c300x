#include "http_camera_quality.h"
#include "camera_quality.h"
#include "camera_update_guard.h"
#include "http_service_commands.h"
#include "http_util.h"
#include "json_util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int c300x_http_camera_quality_route(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, struct c300x_video *video, const struct request *request,
    c300x_schedule_command_fn schedule)
{
    int post = strcmp(request->method, "POST") == 0;
    int bitrate = 0, fps = 0, has_bitrate, has_fps, has_size, reboot = 1;
    char size[C300X_CAMERA_SIZE_LEN];
    const char *error = "";
    struct c300x_camera_quality *quality;

    if (strcmp(request->path, "/api/v1/maintenance/camera-quality") != 0 || (!post && strcmp(request->method, "GET"))) {
        return 0;
    }
    if (!maintenance_authorized(config, request)) {
        c300x_http_send_json(fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return 1;
    }
    quality = calloc(1, sizeof(*quality));
    if (quality == NULL) {
        return c300x_camera_quality_refuse(fd, 500, "Internal Server Error", "out_of_memory");
    }
    if (!c300x_camera_quality_status(quality, config->video_enabled) && post) {
        free(quality);
        return c300x_camera_quality_refuse(fd, 409, "Conflict", "unsupported");
    }
    if (!post) {
        c300x_camera_quality_reply(fd, 0, quality);
        free(quality);
        return 1;
    }
    has_bitrate = c300x_json_int_field_checked(request->body, "bitrate_kbps", &bitrate);
    has_fps = c300x_json_int_field_checked(request->body, "fps", &fps);
    has_size = c300x_json_string_field_checked(request->body, "size", size, sizeof(size));
    error = !confirm_matches(request, "apply_camera_quality") ? NULL : has_bitrate < 0 ? "invalid_bitrate"
        : has_fps < 0 ? "invalid_fps" : has_size < 0 ? "invalid_size"
        : has_bitrate == 0 && has_fps == 0 && has_size == 0 ? "value_required" : "";
    if (error == NULL || error[0] != '\0') {
        free(quality);
        if (error != NULL) return c300x_camera_quality_refuse(fd, 400, "Bad Request", error);
        c300x_http_send_json(fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return 1;
    }
    if (c300x_camera_update_media_busy(video)) {
        free(quality);
        return c300x_camera_quality_refuse(fd, 409, "Conflict", "media_session_active");
    }
    if (!c300x_camera_quality_apply(quality, has_bitrate ? bitrate : quality->saved.bitrate_kbps,
            has_fps ? fps : quality->saved.fps, has_size ? size : NULL, &error)) {
        free(quality);
        return c300x_camera_quality_error(fd, error);
    }
    if (quality->changed) owner->record_write(owner->write_context, "camera_quality", "apply");
    (void)c300x_json_bool_field(request->body, "reboot", &reboot);
    if (reboot && config->maintenance_reboot_enabled && quality->restart_required) {
        c300x_http_service_reboot(owner, fd, config, schedule, c300x_camera_quality_reply, quality, free);
    } else {
        c300x_camera_quality_reply(fd, 0, quality);
        free(quality);
    }
    return 1;
}
