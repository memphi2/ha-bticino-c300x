#include "video_control.h"

#include <string.h>

#include "video_rtsp.h"

static void execute(void *context)
{
    struct c300x_video_control_job *job = context;

    job->result = 1;
    switch (job->op) {
    case C300X_VIDEO_CONTROL_ACTIVATE:
        job->result = c300x_video_activate(job->video, job->argument);
        break;
    case C300X_VIDEO_CONTROL_STOP:
        c300x_video_stop(job->video);
        break;
    case C300X_VIDEO_CONTROL_ANSWER:
        job->result = c300x_video_doorbell_call_answer(job->video);
        break;
    case C300X_VIDEO_CONTROL_HANGUP:
        c300x_video_doorbell_call_hangup(job->video);
        break;
    case C300X_VIDEO_CONTROL_HOME_START:
        job->result = c300x_video_home_call_start(job->video, job->argument);
        break;
    case C300X_VIDEO_CONTROL_HOME_STOP:
        c300x_video_home_call_stop(job->video);
        break;
    }
}

static int starts_something(enum c300x_video_control_op op)
{
    return op == C300X_VIDEO_CONTROL_ACTIVATE || op == C300X_VIDEO_CONTROL_ANSWER
        || op == C300X_VIDEO_CONTROL_HOME_START;
}

static void reap(struct c300x_video_control *control)
{
    control->has_result = c300x_request_worker_reap(&control->worker);
}

void c300x_video_control_settle(struct c300x_video_control *control)
{
    if (control->worker.running) {
        c300x_request_worker_wait(&control->worker);
        reap(control);
    }
}

static int run_here(struct c300x_video *video, enum c300x_video_control_op op, int argument)
{
    struct c300x_video_control_job job = {.video = video, .op = op, .argument = argument};

    execute(&job);
    return job.result;
}

enum c300x_video_control_state c300x_video_control_run(
    struct c300x_video_control *control, struct c300x_video *video,
    enum c300x_video_control_op op, int argument, int *result, const char **error)
{
    struct c300x_request_worker *worker = &control->worker;

    if (worker->armed_fd < 0) {
        /* No wake pipe: on the loop, as before. */
        *result = run_here(video, op, argument);
        return C300X_VIDEO_CONTROL_DONE;
    }
    if (worker->deferred) {
        return C300X_VIDEO_CONTROL_DEFERRED;
    }
    switch (c300x_request_worker_turn(worker)) {
    case C300X_REQUEST_WORKER_FULL:
        *error = "media_busy";
        return C300X_VIDEO_CONTROL_REFUSED;
    case C300X_REQUEST_WORKER_WAIT:
        return C300X_VIDEO_CONTROL_DEFERRED;
    case C300X_REQUEST_WORKER_MINE:
        break;
    }
    if (control->has_result && control->job.op == op && control->job.argument == argument) {
        *result = control->job.result;
        return C300X_VIDEO_CONTROL_DONE;
    }
    if (worker->running) {
        worker->deferred = 1;
        return C300X_VIDEO_CONTROL_DEFERRED;
    }
    if (c300x_request_worker_caller_left(worker) && starts_something(op)) {
        /* Nobody waits for it any more: no stream or call starts that late. */
        *error = "client_gone";
        return C300X_VIDEO_CONTROL_REFUSED;
    }
    control->has_result = 0;
    control->job = (struct c300x_video_control_job){.video = video, .op = op, .argument = argument};
    if (!c300x_request_worker_start(worker)) {
        /* No thread: on the loop, as before. Kept, should the handler run again. */
        execute(&control->job);
        control->has_result = 1;
        *result = control->job.result;
        return C300X_VIDEO_CONTROL_DONE;
    }
    return C300X_VIDEO_CONTROL_DEFERRED;
}

int c300x_video_control_init(struct c300x_video_control *control, struct c300x_request_queue *queue)
{
    memset(control, 0, sizeof(*control));
    return c300x_request_worker_init(&control->worker, queue, execute, &control->job, 1024 * 1024);
}

void c300x_video_control_close(struct c300x_video_control *control)
{
    c300x_video_control_settle(control);
    c300x_request_worker_close(&control->worker);
}

int c300x_video_control_prepare(struct c300x_video_control *control, struct pollfd *fd)
{
    return c300x_request_worker_prepare(&control->worker, fd);
}

void c300x_video_control_tick(struct c300x_video_control *control, const struct pollfd *fd)
{
    if (c300x_request_worker_finished(&control->worker, fd)) {
        reap(control);
    }
}

void c300x_video_control_begin(struct c300x_video_control *control, int client_fd)
{
    c300x_request_worker_begin(&control->worker, client_fd);
}

int c300x_video_control_deferred(const struct c300x_video_control *control)
{
    return control->worker.deferred;
}

void c300x_video_control_end(struct c300x_video_control *control, int deferred)
{
    if (c300x_request_worker_end(&control->worker, deferred)) {
        control->has_result = 0;
    }
}

void c300x_video_control_abandon(struct c300x_video_control *control, int client_fd)
{
    if (c300x_request_worker_abandon(&control->worker, client_fd)) {
        control->has_result = 0;
    }
}
