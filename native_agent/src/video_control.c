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

static int run_here(struct c300x_video_control *control, struct c300x_video *video,
                    enum c300x_video_control_op op, int argument)
{
    struct c300x_video_control_job job = {.video = video, .op = op, .argument = argument};

    c300x_video_control_settle(control);
    execute(&job);
    return job.result;
}

int c300x_video_control_run(struct c300x_video_control *control, struct c300x_video *video,
                            enum c300x_video_control_op op, int argument, int *result)
{
    struct c300x_request_worker *worker = &control->worker;

    if (worker->armed_fd < 0) {
        *result = run_here(control, video, op, argument);
        return 1;
    }
    if (worker->deferred) {
        return 0;
    }
    switch (c300x_request_worker_turn(worker)) {
    case C300X_REQUEST_WORKER_FULL:
        *result = run_here(control, video, op, argument);
        return 1;
    case C300X_REQUEST_WORKER_WAIT:
        return 0;
    case C300X_REQUEST_WORKER_MINE:
        break;
    }
    if (control->has_result && control->job.op == op && control->job.argument == argument) {
        control->has_result = 0;
        *result = control->job.result;
        return 1;
    }
    if (worker->running) {
        worker->deferred = 1;
        return 0;
    }
    if (c300x_request_worker_caller_left(worker) && starts_something(op)) {
        /* Nobody waits for it any more: no stream or call starts that late. */
        *result = 0;
        return 1;
    }
    control->has_result = 0;
    control->job = (struct c300x_video_control_job){.video = video, .op = op, .argument = argument};
    if (!c300x_request_worker_start(worker)) {
        execute(&control->job);
        *result = control->job.result;
        return 1;
    }
    return 0;
}

int c300x_video_control_init(struct c300x_video_control *control)
{
    memset(control, 0, sizeof(*control));
    return c300x_request_worker_init(&control->worker, execute, &control->job, 1024 * 1024);
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

int c300x_video_control_end(struct c300x_video_control *control)
{
    int answered;
    int deferred = c300x_request_worker_end(&control->worker, &answered);

    if (answered) {
        control->has_result = 0;
    }
    return deferred;
}

void c300x_video_control_abandon(struct c300x_video_control *control, int client_fd)
{
    if (c300x_request_worker_abandon(&control->worker, client_fd)) {
        control->has_result = 0;
    }
}
