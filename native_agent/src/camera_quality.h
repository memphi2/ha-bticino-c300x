#ifndef C300X_CAMERA_QUALITY_H
#define C300X_CAMERA_QUALITY_H

#include <stddef.h>

/*
 * Bit rate and frame rate of the high-resolution camera stream. The device
 * keeps them as BitrateRtpH and FpsRtpH in the [Answering Machine] section of
 * its bt_answering_machine settings file. That file is on the read-only root
 * file system and is read only when the device starts, so a change is written
 * there (one backup of the original is kept on the data partition) and takes
 * effect with the next device restart. Firmware 3.0.x has no high-resolution
 * stream; the caller does not offer the setting there.
 */

#define C300X_CAMERA_BITRATE_MIN 300  /* kbit/s */
#define C300X_CAMERA_BITRATE_MAX 3000 /* the device refuses more */
#define C300X_CAMERA_FPS_MIN 5
#define C300X_CAMERA_FPS_MAX 25 /* the camera is PAL */

struct c300x_camera_quality {
    int supported;        /* the file has both values */
    int bitrate_kbps;
    int fps;
    int restart_required; /* the file was written after the device started */
    int changed;          /* the last apply wrote the file */
    int remount_ro_failed;
};

int c300x_camera_quality_read(struct c300x_camera_quality *quality);
/* A value of zero keeps what the file has. error names the failed step. */
int c300x_camera_quality_apply(struct c300x_camera_quality *quality, int bitrate_kbps, int fps,
    const char **error);
/* Puts back the two values of the original file, when one was backed up. */
int c300x_camera_quality_remove_patches(const char **error);
void c300x_camera_quality_body(const struct c300x_camera_quality *quality, char *body, size_t body_len);

#endif
