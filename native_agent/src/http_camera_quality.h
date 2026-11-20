#ifndef C300X_HTTP_CAMERA_QUALITY_H
#define C300X_HTTP_CAMERA_QUALITY_H

#include "http_service_commands.h"

/* GET and POST /api/v1/maintenance/camera-quality. unsupported is nonzero on
 * a device without a high-resolution stream. Like the audio codec switch, a
 * change restarts the device unless the request sends "reboot": false or
 * reboot maintenance is disabled. */
int c300x_http_camera_quality_route(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, int unsupported, const struct request *request,
    c300x_schedule_command_fn schedule);

#endif
