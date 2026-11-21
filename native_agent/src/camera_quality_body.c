#include "camera_quality.h"
#include "http_util.h"

#include <stdio.h>
#include <string.h>

void c300x_camera_quality_body(const struct c300x_camera_quality *quality, int rebooting,
    char *body, size_t body_len)
{
    char offered[96] = "";
    size_t used = 0;
    const char *name;
    const struct c300x_camera_limits *limits = c300x_camera_quality_limits(quality->low);

    for (size_t i = 0; (name = c300x_camera_quality_size_at(quality->low, i)) != NULL && used < sizeof(offered); i++) {
        used += (size_t)snprintf(offered + used, sizeof(offered) - used, "%s\"%s\"", i ? "," : "", name);
    }
    snprintf(body, body_len,
        "{\"ok\":true,\"supported\":%s,\"stream\":\"%s\",\"bitrate_kbps\":%d,\"fps\":%d,\"size\":\"%s\","
        "\"running_bitrate_kbps\":%d,\"running_fps\":%d,\"running_size\":\"%s\","
        "\"bitrate_min\":%d,\"bitrate_max\":%d,\"fps_min\":%d,\"fps_max\":%d,\"sizes\":[%s],"
        "\"restart_required\":%s,\"changed\":%s,\"remount_ro_failed\":%s,\"rebooting\":%s}\n",
        quality->supported ? "true" : "false", quality->low ? "low" : "high",
        quality->saved.bitrate_kbps, quality->saved.fps, quality->size,
        quality->running.bitrate_kbps, quality->running.fps, quality->running_size,
        limits->bitrate_min, limits->bitrate_max, limits->fps_min, limits->fps_max,
        offered, quality->restart_required ? "true" : "false", quality->changed ? "true" : "false",
        quality->remount_ro_failed ? "true" : "false", rebooting ? "true" : "false");
}

void c300x_camera_quality_reply(int fd, int rebooting, void *context)
{
    char body[640];
    c300x_camera_quality_body(context, rebooting, body, sizeof(body));
    c300x_http_send_json(fd, 200, "OK", body);
}
