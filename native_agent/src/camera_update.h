#ifndef C300X_CAMERA_UPDATE_H
#define C300X_CAMERA_UPDATE_H

#include "camera_settings.h"

/* Couple the saved crop/settings and the optional High-geometry binary patch. */
int c300x_camera_update(int low, const struct c300x_camera_values *before,
    const struct c300x_camera_values *after, int geometry_before, int geometry_after,
    const char *settings, const char *crop, int *ro_failed, const char **error);

#endif
