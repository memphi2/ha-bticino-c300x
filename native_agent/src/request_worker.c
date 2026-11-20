#include "request_worker.h"

#include <errno.h>
#include <string.h>
#include <unistd.h>

static void *run(void *context)
{
    struct c300x_request_worker *worker = context;
    char done = 1;

    worker->execute(worker->job);
    /* The loop reads the job only after this byte; a pipe of one byte per
     * job cannot be full. */
    while (write(worker->wake[1], &done, 1) < 0 && errno == EINTR) {
    }
    return NULL;
}

int c300x_request_worker_init(struct c300x_request_worker *worker, struct c300x_request_queue *queue,
                              void (*execute)(void *job), void *job, size_t stack_bytes)
{
    memset(worker, 0, sizeof(*worker));
    worker->owner_fd = C300X_REQUEST_WORKER_FREE;
    worker->armed_fd = -1;
    worker->queue = queue;
    worker->execute = execute;
    worker->job = job;
    worker->stack_bytes = stack_bytes;
    return c300x_openwebnet_wake_pipe(worker->wake);
}

void c300x_request_worker_close(struct c300x_request_worker *worker)
{
    for (int index = 0; index < 2; index++) {
        if (worker->wake[index] >= 0) {
            close(worker->wake[index]);
            worker->wake[index] = -1;
        }
    }
}

int c300x_request_worker_prepare(struct c300x_request_worker *worker, struct pollfd *fd)
{
    *fd = (struct pollfd){.fd = worker->running ? worker->wake[0] : -1, .events = POLLIN};
    if (worker->reaped || (worker->owner_fd == C300X_REQUEST_WORKER_FREE
                           && c300x_request_queue_first(worker->queue, worker) >= 0)) {
        worker->reaped = 0;
        return 0;
    }
    return -1;
}

int c300x_request_worker_finished(const struct c300x_request_worker *worker, const struct pollfd *fd)
{
    return worker->running && fd->fd == worker->wake[0] && (fd->revents & POLLIN) != 0;
}

void c300x_request_worker_wait(const struct c300x_request_worker *worker)
{
    if (worker->running) {
        c300x_openwebnet_wait_readable(worker->wake[0]);
    }
}

int c300x_request_worker_reap(struct c300x_request_worker *worker)
{
    char done;

    /* After the wake byte this only waits for the thread to leave; before
     * it, for the rest of the job. */
    (void)pthread_join(worker->thread, NULL);
    while (read(worker->wake[0], &done, 1) < 0 && errno == EINTR) {
    }
    worker->running = 0;
    worker->reaped = 1;
    if (worker->owner_fd == C300X_REQUEST_WORKER_GONE) {
        worker->owner_fd = C300X_REQUEST_WORKER_FREE;
        return 0;
    }
    return 1;
}

void c300x_request_worker_begin(struct c300x_request_worker *worker, int client_fd)
{
    if (worker->wake[0] >= 0) {
        worker->armed_fd = client_fd;
        worker->deferred = 0;
        worker->waited = 0;
    }
}

int c300x_request_worker_abandon(struct c300x_request_worker *worker, int client_fd)
{
    (void)c300x_request_queue_remove(worker->queue, worker, client_fd);
    if (worker->owner_fd != client_fd) {
        return 0;
    }
    worker->owner_fd = worker->running ? C300X_REQUEST_WORKER_GONE : C300X_REQUEST_WORKER_FREE;
    worker->reaped = 1; /* a request held back for this one is offered again */
    return 1;
}

int c300x_request_worker_end(struct c300x_request_worker *worker, int deferred)
{
    int answered = 0;

    if (worker->armed_fd >= 0 && !deferred) {
        /* Answered. A job it no longer waits for still runs to its end. */
        answered = c300x_request_worker_abandon(worker, worker->armed_fd);
    }
    worker->armed_fd = -1;
    worker->deferred = 0;
    return answered;
}

enum c300x_request_worker_turn c300x_request_worker_turn(struct c300x_request_worker *worker)
{
    int first = c300x_request_queue_first(worker->queue, worker);

    if (worker->owner_fd == worker->armed_fd) {
        return C300X_REQUEST_WORKER_MINE;
    }
    if (worker->owner_fd == C300X_REQUEST_WORKER_FREE && (first < 0 || first == worker->armed_fd)) {
        worker->waited = c300x_request_queue_remove(worker->queue, worker, worker->armed_fd);
        return C300X_REQUEST_WORKER_MINE;
    }
    /* A waiting request whose caller left gives its place to this one. */
    if (!c300x_request_queue_add(worker->queue, worker, worker->armed_fd)
        && !(c300x_request_queue_drop_departed(worker->queue)
             && c300x_request_queue_add(worker->queue, worker, worker->armed_fd))) {
        return C300X_REQUEST_WORKER_FULL;
    }
    worker->deferred = 1;
    return C300X_REQUEST_WORKER_WAIT;
}

int c300x_request_worker_caller_left(struct c300x_request_worker *worker)
{
    int waited = worker->waited;

    /* Asked once, before the first job; later jobs of the request are not held up. */
    worker->waited = 0;
    return waited && c300x_openwebnet_caller_left(worker->armed_fd);
}

int c300x_request_worker_start(struct c300x_request_worker *worker)
{
    worker->owner_fd = worker->armed_fd;
    if (!c300x_openwebnet_worker_start(&worker->thread, run, worker, worker->stack_bytes)) {
        return 0;
    }
    worker->running = 1;
    worker->deferred = 1;
    return 1;
}
