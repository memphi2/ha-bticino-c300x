#ifndef C300X_HTTP_MEDIA_ACTIONS_H
#define C300X_HTTP_MEDIA_ACTIONS_H

#include "http_request.h"
#include "video_control.h"

/* The API actions that start or end a stream or a call. Each may return
 * without an answer: its operation runs beside the loop and the request is
 * handled again when it is done. */
void c300x_http_doorbell_video_activate(int client_fd, struct c300x_video_control *control,
                                        struct c300x_video *video, const struct request *request);
void c300x_http_doorbell_video_stop(int client_fd, struct c300x_video_control *control, struct c300x_video *video);
void c300x_http_doorbell_call_answer(int client_fd, struct c300x_video_control *control,
                                     struct c300x_video *video, const struct request *request);
void c300x_http_doorbell_call_hangup(int client_fd, struct c300x_video_control *control, struct c300x_video *video);
void c300x_http_home_call_start(int client_fd, struct c300x_video_control *control,
                                struct c300x_video *video, const struct request *request);
void c300x_http_home_call_stop(int client_fd, struct c300x_video_control *control, struct c300x_video *video);

#endif
