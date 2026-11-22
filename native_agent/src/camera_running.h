#ifndef C300X_CAMERA_RUNNING_H
#define C300X_CAMERA_RUNNING_H

#include "camera_settings.h"

/* Boot-scoped configuration, preserved when only the agent restarts. */
void c300x_camera_running_load(int low, const char *settings, const char *crop,
    struct c300x_camera_values *values);
/* Current executable observation only; does not load or change the boot note. */
int c300x_camera_running_current_geometry(void);
/* Before any saved configuration/binary change, persist its boot baseline.
 * Failure must abort the update; it is not evidence that a reboot is needed. */
int c300x_camera_running_prepare(const struct c300x_camera_values *baseline, const char **error);
/* Query the same process generation as the boot note. Returns pending saved
 * changes independently of whether running values can still be established.
 * Unknown values are zero, unknown geometry is C300X_MEDIA_GEOMETRY_UNKNOWN. */
int c300x_camera_running_read(int low, const struct c300x_camera_values *baseline,
    const struct c300x_camera_values *saved, int saved_geometry,
    struct c300x_camera_values *values, int *geometry);

#endif
