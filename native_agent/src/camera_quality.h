#ifndef C300X_CAMERA_QUALITY_H
#define C300X_CAMERA_QUALITY_H

#include <stddef.h>

/*
 * Bit rate and frame rate of the high-resolution camera stream. The device
 * keeps them as BitrateRtpH and FpsRtpH in the [Answering Machine] section of
 * its bt_answering_machine settings file. That file is on the read-only root
 * file system and is read only when the device starts, so a change is written
 * there the way the audio codec switch writes its files (one backup of the
 * original on the data partition, an atomic write, the root writable only
 * around it, the result read back) and takes effect with a device restart.
 * Firmware 3.0.x has no high-resolution stream; the caller does not offer the
 * setting there.
 */

#define C300X_CAMERA_BITRATE_MIN 300  /* kbit/s */
#define C300X_CAMERA_BITRATE_MAX 3000 /* the device refuses more */
#define C300X_CAMERA_FPS_MIN 5
#define C300X_CAMERA_FPS_MAX 25 /* the camera is PAL */

struct c300x_camera_quality {
    int supported;        /* the file has each value exactly once */
    int bitrate_kbps;     /* in the file */
    int fps;
    int running_bitrate_kbps; /* what the device started with; 0 if unknown */
    int running_fps;
    int restart_required; /* the file differs from what the device runs */
    int changed;          /* the last apply wrote the file */
    int remount_ro_failed;
};

/* Called once when the agent starts. */
void c300x_camera_quality_note_running(void);
int c300x_camera_quality_read(struct c300x_camera_quality *quality);
/* Writes both values when they are in range. error names the failed step. */
int c300x_camera_quality_apply(struct c300x_camera_quality *quality, int bitrate_kbps, int fps,
    const char **error);
/* Puts back the two values of the original file, when one was backed up. A
 * file that lost the values meanwhile is left alone. */
int c300x_camera_quality_remove_patches(const char **error);
void c300x_camera_quality_body(const struct c300x_camera_quality *quality, int rebooting,
    char *body, size_t body_len);

#endif
