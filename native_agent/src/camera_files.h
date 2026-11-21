#ifndef C300X_CAMERA_FILES_H
#define C300X_CAMERA_FILES_H

#include "camera_settings.h"

/* The cut file's backup has a name of its own: the audio codec switch keeps
 * one of the same file and puts back only its own lines from it. */
#define C300X_CAMERA_CROP_BACKUP "stack_open.xml.camera"

/*
 * Writes camera values to the device's files the way the audio codec switch
 * writes its files: one backup of each original on the data partition, an
 * atomic write, the root writable only around it. The settings file is
 * written when one of its four values changes, the cut file (high stream)
 * when the cut changes; everything else in them stays.
 */
/* The whole text of a file, in memory the caller frees; NULL when it cannot
 * be read or holds a NUL. */
char *c300x_camera_file_text(const char *path);
/* The values of the settings file and, for the high stream, the cut. */
int c300x_camera_files_read(int low, const char *settings_path, const char *crop_path,
    struct c300x_camera_values *values);
int c300x_camera_files_write(int low, const struct c300x_camera_values *now,
    const struct c300x_camera_values *target, const char *settings_path, const char *crop_path,
    int *remount_ro_failed, const char **error);

#endif
