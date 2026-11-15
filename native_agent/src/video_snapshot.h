#ifndef C300X_VIDEO_SNAPSHOT_H
#define C300X_VIDEO_SNAPSHOT_H

#include <stddef.h>

#define C300X_SNAPSHOT_MIN_SIZE 64U
#define C300X_SNAPSHOT_MAX_WIDTH 800U
#define C300X_SNAPSHOT_MAX_HEIGHT 480U

/* Caller owns *data on success. No capture starts more than once per 2 seconds.
   width and height give the exact image size; both zero keeps the display's. */
enum c300x_snapshot_result {
    C300X_SNAPSHOT_OK,
    C300X_SNAPSHOT_UNAVAILABLE,
    C300X_SNAPSHOT_THROTTLED
};
enum c300x_snapshot_result c300x_video_snapshot(
    unsigned char **data, size_t *size, unsigned int width, unsigned int height);

#endif
