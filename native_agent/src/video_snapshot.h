#ifndef C300X_VIDEO_SNAPSHOT_H
#define C300X_VIDEO_SNAPSHOT_H

#include <stddef.h>

/* Caller owns *data on success. No capture starts more than once per 2 seconds. */
enum c300x_snapshot_result {
    C300X_SNAPSHOT_OK,
    C300X_SNAPSHOT_UNAVAILABLE,
    C300X_SNAPSHOT_THROTTLED
};
enum c300x_snapshot_result c300x_video_snapshot(unsigned char **data, size_t *size);

#endif
