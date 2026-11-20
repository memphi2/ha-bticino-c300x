#include "camera_quality.h"
#include "http_util.h"

#include <stdio.h>
#include <string.h>

struct size_choice {
    const char *name;
    int width;
    int height;
};

/* High stream: the device crops the camera picture when Width is more than
 * 1.5 times Height (800x480 from the factory gives 688x480) and sends the
 * whole 720x576 picture otherwise; no other size comes out. */
static const struct size_choice HIGH_SIZES[] = {
    {"688x480", 800, 480},
    {"720x576", 720, 480},
};
/* Low stream: the device scales the 720x576 camera picture to WidthLow x
 * HeightLow; no larger, both multiples of 16 for the encoder. */
static const struct size_choice LOW_SIZES[] = {
    {"352x288", 352, 288}, {"400x288", 400, 288}, {"640x480", 640, 480},
    {"704x576", 704, 576}, {"720x576", 720, 576},
};
/* High: 25 fps is not 25 for the device, it drops its frame rate control
 * and sends about 8 fps. Low (firmware 3.0.x): the device lowers a bit rate
 * at run time and raises it again only up to 2000 kbit/s. */
static const struct c300x_camera_limits LIMITS[2] = {{300, 3000, 5, 24}, {100, 2000, 5, 25}};

const struct c300x_camera_limits *c300x_camera_quality_limits(int low)
{
    return &LIMITS[low != 0];
}

static const struct size_choice *sizes(int low, size_t *count)
{
    *count = low ? sizeof(LOW_SIZES) / sizeof(LOW_SIZES[0]) : sizeof(HIGH_SIZES) / sizeof(HIGH_SIZES[0]);
    return low ? LOW_SIZES : HIGH_SIZES;
}

void c300x_camera_quality_size_name(int low, const struct c300x_camera_values *values,
    char *out, size_t out_len)
{
    if (values->width <= 0 || values->height <= 0) {
        snprintf(out, out_len, "%s", "");
    } else if (low) {
        snprintf(out, out_len, "%dx%d", values->width, values->height);
    } else {
        snprintf(out, out_len, "%s", values->width * 2 > values->height * 3 ? "688x480" : "720x576");
    }
}

int c300x_camera_quality_size_values(int low, const char *name, struct c300x_camera_values *values)
{
    size_t count;
    const struct size_choice *choices = sizes(low, &count);

    for (size_t i = 0; i < count; i++) {
        if (strcmp(choices[i].name, name) == 0) {
            values->width = choices[i].width;
            values->height = choices[i].height;
            return 1;
        }
    }
    return 0;
}

void c300x_camera_quality_body(const struct c300x_camera_quality *quality, int rebooting,
    char *body, size_t body_len)
{
    char offered[96] = "";
    size_t count, used = 0;
    const struct size_choice *choices = sizes(quality->low, &count);
    const struct c300x_camera_limits *limits = c300x_camera_quality_limits(quality->low);

    for (size_t i = 0; i < count && used < sizeof(offered); i++) {
        used += (size_t)snprintf(offered + used, sizeof(offered) - used, "%s\"%s\"", i ? "," : "",
            choices[i].name);
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
