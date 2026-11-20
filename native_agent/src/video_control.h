#ifndef C300X_VIDEO_CONTROL_H
#define C300X_VIDEO_CONTROL_H

#include "request_worker.h"

struct c300x_video;

enum c300x_video_control_op {
    C300X_VIDEO_CONTROL_ACTIVATE = 1, /* argument: with audio */
    C300X_VIDEO_CONTROL_STOP,
    C300X_VIDEO_CONTROL_ANSWER,
    C300X_VIDEO_CONTROL_HANGUP,
    C300X_VIDEO_CONTROL_HOME_START, /* argument: duration in seconds */
    C300X_VIDEO_CONTROL_HOME_STOP,
};

struct c300x_video_control_job {
    struct c300x_video *video;
    enum c300x_video_control_op op;
    int argument;
    int result;
};

/* Keeps the media operations of API requests off the HTTP loop: they wait
 * for SIP answers, for clients to drain and for media threads to end.
 *
 * One operation runs at a time, as before. The first runs on the request
 * worker while its request stays in the client slot; further requests wait
 * their turn. Whatever cannot wait there runs on the loop, as before, after
 * the running operation: a caller that is not an API request, a request
 * beyond the waiting places, and any request when no thread can start. */
struct c300x_video_control {
    struct c300x_request_worker worker;
    struct c300x_video_control_job job;
    int has_result;
};

int c300x_video_control_init(struct c300x_video_control *control);
/* Finishes a running operation: the media owner must outlive it. */
void c300x_video_control_close(struct c300x_video_control *control);
int c300x_video_control_prepare(struct c300x_video_control *control, struct pollfd *fd);
void c300x_video_control_tick(struct c300x_video_control *control, const struct pollfd *fd);
void c300x_video_control_begin(struct c300x_video_control *control, int client_fd);
/* Nonzero: the request is deferred; nothing was answered and it runs again. */
int c300x_video_control_end(struct c300x_video_control *control);
void c300x_video_control_abandon(struct c300x_video_control *control, int client_fd);
/* Nonzero with *result set, or zero: the handler returns without an answer. */
int c300x_video_control_run(struct c300x_video_control *control, struct c300x_video *video,
                            enum c300x_video_control_op op, int argument, int *result);
/* Let a running operation end before the loop itself changes the media state. */
void c300x_video_control_settle(struct c300x_video_control *control);

#endif
