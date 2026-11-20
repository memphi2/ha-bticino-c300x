#include "http_camera_quality.h"
#include "camera_quality.h"
#include "http_service_commands.h"
#include "http_util.h"
#include "json_util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void reply_quality(int fd, int rebooting, void *context)
{
    char body[512];
    c300x_camera_quality_body(context, rebooting, body, sizeof(body));
    c300x_http_send_json(fd, 200, "OK", body);
}

static int refuse(int fd, int status, const char *reason, const char *error)
{
    char body[160];
    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"camera_quality_%s\"}\n", error);
    c300x_http_send_json(fd, status, reason, body);
    return 1;
}

int c300x_http_camera_quality_route(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, int unsupported, const struct request *request,
    c300x_schedule_command_fn schedule)
{
    int post = strcmp(request->method, "POST") == 0;
    int bitrate = 0, fps = 0, has_bitrate, has_fps, reboot = 1;
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
        return refuse(fd, 500, "Internal Server Error", "out_of_memory");
    }
    if (unsupported || !config->video_enabled || !c300x_camera_quality_read(quality)) {
        if (post) free(quality);
        if (post) return refuse(fd, 409, "Conflict", "unsupported");
        memset(quality, 0, sizeof(*quality));
    }
    if (!post) {
        reply_quality(fd, 0, quality);
        free(quality);
        return 1;
    }
    has_bitrate = c300x_json_int_field_checked(request->body, "bitrate_kbps", &bitrate);
    has_fps = c300x_json_int_field_checked(request->body, "fps", &fps);
    error = !confirm_matches(request, "apply_camera_quality") ? NULL : has_bitrate < 0 ? "invalid_bitrate"
        : has_fps < 0 ? "invalid_fps" : has_bitrate == 0 && has_fps == 0 ? "value_required" : "";
    if (error == NULL || error[0] != '\0') {
        free(quality);
        if (error != NULL) return refuse(fd, 400, "Bad Request", error);
        c300x_http_send_json(fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return 1;
    }
    /* A value not sent stays what the file has. */
    if (!c300x_camera_quality_apply(quality, has_bitrate ? bitrate : quality->bitrate_kbps,
            has_fps ? fps : quality->fps, &error)) {
        int refused = strcmp(error, "out_of_range") == 0;
        free(quality);
        return refuse(fd, refused ? 400 : 500, refused ? "Bad Request" : "Internal Server Error", error);
    }
    if (quality->changed) owner->record_write(owner->write_context, "camera_quality", "apply");
    (void)c300x_json_bool_field(request->body, "reboot", &reboot);
    if (reboot && config->maintenance_reboot_enabled && quality->restart_required) {
        c300x_http_service_reboot(owner, fd, config, schedule, reply_quality, quality, free);
    } else {
        reply_quality(fd, 0, quality);
        free(quality);
    }
    return 1;
}
