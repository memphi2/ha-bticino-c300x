#ifndef C300X_HTTP_CAMERA_QUALITY_H
#define C300X_HTTP_CAMERA_QUALITY_H

#include "http_maintenance.h"

/* GET and POST /api/v1/maintenance/camera-quality. unsupported is nonzero on
 * a device without a high-resolution stream. A change takes effect with the
 * next device restart, which the caller asks for separately. */
int c300x_http_camera_quality_route(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, int unsupported, const struct request *request);

#endif
