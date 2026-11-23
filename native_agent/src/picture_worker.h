#ifndef C300X_PICTURE_WORKER_H
#define C300X_PICTURE_WORKER_H

#include "video_control.h"
#include "video_rtsp.h"

enum picture_route { PICTURE_LEGACY, PICTURE_DIRECT, PICTURE_DEFERRED, PICTURE_BUSY,
                     PICTURE_UNAVAILABLE, PICTURE_NOT_APPLIED };
void picture_worker_execute(struct c300x_video_control_job *job);
/* A null command asks for capability only; it never reads an idle source. */
enum picture_route picture_worker_request(struct c300x_video_control *control,
    struct c300x_video *video, const struct c300x_video_status *status,
    const struct c300x_config *config, const struct picture_command *command, int values[3]);

#endif
