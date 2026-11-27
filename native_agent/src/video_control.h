#ifndef C300X_VIDEO_CONTROL_H
#define C300X_VIDEO_CONTROL_H

#include "request_worker.h"
#include "media_unit.h"

struct c300x_video;

enum c300x_video_control_op {
    C300X_VIDEO_CONTROL_ACTIVATE = 1, /* argument: with audio; where: the unit's DEVADDR, "" the default */
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
    char where[C300X_MEDIA_DEVADDR_LEN];
    int result;
};

enum c300x_video_control_state {
    C300X_VIDEO_CONTROL_DONE,
    C300X_VIDEO_CONTROL_DEFERRED, /* the handler returns without an answer */
    C300X_VIDEO_CONTROL_REFUSED,  /* not run; the handler answers with the error */
};

/* Keeps the media operations of API requests off the HTTP loop: they wait
 * for SIP answers, for clients to drain and for media threads to end.
 *
 * The operations of API requests run one at a time, in the order the
 * requests arrived: the first on the request worker while its request stays
 * in the client slot, further requests wait in the queue. A request that
 * finds no place there is refused with media_busy. Only when no thread can
 * start does an operation run on the loop, as it did before. Stops from
 * elsewhere (the CPU watchdog, a departing RTSP client) do not come through
 * here and may run beside an operation, as they always could. */
struct c300x_video_control {
    struct c300x_request_worker worker;
    struct c300x_video_control_job job;
    int has_result; /* kept until the request is answered: its handler may run more than once more */
};

int c300x_video_control_init(struct c300x_video_control *control, struct c300x_request_queue *queue);
/* Finishes a running operation: the media owner must outlive it. */
void c300x_video_control_close(struct c300x_video_control *control);
int c300x_video_control_prepare(struct c300x_video_control *control, struct pollfd *fd);
void c300x_video_control_tick(struct c300x_video_control *control, const struct pollfd *fd);
void c300x_video_control_begin(struct c300x_video_control *control, int client_fd);
int c300x_video_control_deferred(const struct c300x_video_control *control);
/* deferred: the request runs again, here or for the OpenWebNet worker. */
void c300x_video_control_end(struct c300x_video_control *control, int deferred);
void c300x_video_control_abandon(struct c300x_video_control *control, int client_fd);
/* DONE sets *result, REFUSED sets *error. where may be NULL (""). */
enum c300x_video_control_state c300x_video_control_run(
    struct c300x_video_control *control, struct c300x_video *video,
    enum c300x_video_control_op op, int argument, const char *where, int *result, const char **error);
/* Let a running operation end before the loop itself changes the media state. */
void c300x_video_control_settle(struct c300x_video_control *control);

#endif
