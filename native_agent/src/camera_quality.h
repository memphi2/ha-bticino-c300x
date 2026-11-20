#ifndef C300X_CAMERA_QUALITY_H
#define C300X_CAMERA_QUALITY_H

#include "camera_settings.h"

#include <stddef.h>

/*
 * Bit rate, frame rate and size of the camera stream Home Assistant gets: the
 * high-resolution stream, or on firmware 3.0.x (Qt 5 display) the low one,
 * the only stream it sends. The device keeps them in the [Answering Machine]
 * section of its bt_answering_machine settings file, on the read-only root
 * file system, and reads them only when it starts. A change is written there
 * the way the audio codec switch writes its files (one backup of the
 * original on the data partition, an atomic write, the root writable only
 * around it, the result read back) and takes effect with a device restart.
 */

#define C300X_CAMERA_SIZE_LEN 16

/* The values offered for a stream. */
struct c300x_camera_limits {
    int bitrate_min; /* kbit/s */
    int bitrate_max;
    int fps_min;
    int fps_max;
};

struct c300x_camera_quality {
    int supported; /* the file has each value exactly once */
    int low;       /* the values of the low stream (firmware 3.0.x) */
    struct c300x_camera_values saved;   /* in the file */
    struct c300x_camera_values running; /* what the device started with; 0 if unknown */
    char size[C300X_CAMERA_SIZE_LEN];   /* the stream size the saved values give */
    char running_size[C300X_CAMERA_SIZE_LEN];
    int restart_required; /* the file differs from what the device runs */
    int changed;          /* the last apply wrote the file */
    int remount_ro_failed;
};

/* Called once when the agent starts. */
void c300x_camera_quality_note_running(void);
int c300x_camera_quality_read(struct c300x_camera_quality *quality);
/* As _read, but with video off or no values only names the stream; returns
 * whether the setting is supported. */
int c300x_camera_quality_status(struct c300x_camera_quality *quality, int video_enabled);
/* Writes the values when they are in range; size NULL keeps the size.
 * error names the failed step. */
int c300x_camera_quality_apply(struct c300x_camera_quality *quality, int bitrate_kbps, int fps,
    const char *size, const char **error);
/* Puts back the values of the original file, when one was backed up. A file
 * that lost them meanwhile is left alone. */
int c300x_camera_quality_remove_patches(const char **error);

/* camera_quality_body.c: the limits and sizes offered and the JSON answer. */
const struct c300x_camera_limits *c300x_camera_quality_limits(int low);
void c300x_camera_quality_size_name(int low, const struct c300x_camera_values *values,
    char *out, size_t out_len);
/* Sets width and height for an offered size; 0 for any other name. */
int c300x_camera_quality_size_values(int low, const char *name, struct c300x_camera_values *values);
void c300x_camera_quality_body(const struct c300x_camera_quality *quality, int rebooting,
    char *body, size_t body_len);
/* Sends that answer; context is the quality. */
void c300x_camera_quality_reply(int fd, int rebooting, void *context);

#endif
