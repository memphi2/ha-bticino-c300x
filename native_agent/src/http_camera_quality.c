#include "http_camera_quality.h"
#include "camera_quality.h"
#include "http_util.h"
#include "json_util.h"

#include <stdio.h>
#include <string.h>

static void reply_quality(int fd, const struct c300x_camera_quality *quality)
{
    char body[512];
    c300x_camera_quality_body(quality, body, sizeof(body));
    c300x_http_send_json(fd, 200, "OK", body);
}

int c300x_http_camera_quality_route(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, int unsupported, const struct request *request)
{
    int post = strcmp(request->method, "POST") == 0;
    int bitrate = 0, fps = 0, has_bitrate, has_fps;
    const char *error = "";
    struct c300x_camera_quality quality;
    char body[160];

    if (strcmp(request->path, "/api/v1/maintenance/camera-quality") != 0
        || (!post && strcmp(request->method, "GET") != 0)) {
        return 0;
    }
    if (!maintenance_authorized(config, request)) {
        c300x_http_send_json(fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return 1;
    }
    if (unsupported || !c300x_camera_quality_read(&quality)) {
        if (post) {
            c300x_http_send_json(fd, 409, "Conflict", "{\"ok\":false,\"error\":\"camera_quality_unsupported\"}\n");
        } else {
            memset(&quality, 0, sizeof(quality));
            reply_quality(fd, &quality);
        }
        return 1;
    }
    if (!post) {
        reply_quality(fd, &quality);
        return 1;
    }
    if (!confirm_matches(request, "apply_camera_quality")) {
        c300x_http_send_json(fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return 1;
    }
    has_bitrate = c300x_json_int_field(request->body, "bitrate_kbps", &bitrate);
    has_fps = c300x_json_int_field(request->body, "fps", &fps);
    /* Zero means "keep" below, so it is not a value a caller may send. */
    if ((!has_bitrate && !has_fps) || (has_bitrate && bitrate <= 0) || (has_fps && fps <= 0)) {
        error = "out_of_range";
    } else if (c300x_camera_quality_apply(&quality, bitrate, fps, &error)) {
        error = NULL;
    }
    if (error != NULL) {
        int refused = strcmp(error, "out_of_range") == 0;
        snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"camera_quality_%s\"}\n", error);
        c300x_http_send_json(fd, refused ? 400 : 500, refused ? "Bad Request" : "Internal Server Error", body);
        return 1;
    }
    if (quality.changed) {
        owner->record_write(owner->write_context, "camera_quality", "apply");
    }
    reply_quality(fd, &quality);
    return 1;
}
