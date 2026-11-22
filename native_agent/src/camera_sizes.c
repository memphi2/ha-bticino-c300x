#include "camera_quality.h"

#include <stdio.h>
#include <string.h>

struct size_choice {
    const char *name;
    int width;
    int height;
    int crop[4];
};

/* High stream: with Width more than 1.5 times Height (800x480 from the
 * factory) the device sends the cut of the 720x576 camera picture that
 * stack_open.xml names and shows it over the whole display. The factory cut
 * leaves out top and bottom; 704x576 keeps the whole picture and leaves out
 * only the black edges the camera sends at its sides. */
static const struct size_choice HIGH_SIZES[] = {
    {"688x480", 800, 480, {16, 48, 688, 480}},
    {"704x576", 800, 480, {8, 0, 704, 576}},
    {"960x576", 800, 480, {8, 0, 704, 576}},
};
/* Low stream: the device scales the 720x576 camera picture to WidthLow x
 * HeightLow; no larger, both multiples of 16 for the encoder. */
static const struct size_choice LOW_SIZES[] = {
    {"352x288", 352, 288, {0}}, {"400x288", 400, 288, {0}}, {"640x480", 640, 480, {0}},
    {"704x576", 704, 576, {0}}, {"720x576", 720, 576, {0}},
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
    } else if (values->width * 2 > values->height * 3) {
        snprintf(out, out_len, "%dx%d", values->crop[2], values->crop[3]);
    } else {
        snprintf(out, out_len, "%s", "720x576"); /* no cut: the whole camera picture */
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
            if (!low) {
                memcpy(values->crop, choices[i].crop, sizeof(values->crop));
            }
            return 1;
        }
    }
    return 0;
}

const char *c300x_camera_quality_size_at(int low, size_t index)
{
    size_t count;
    const struct size_choice *choices = sizes(low, &count);
    return index < count ? choices[index].name : NULL;
}
