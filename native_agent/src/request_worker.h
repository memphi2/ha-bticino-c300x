#ifndef C300X_REQUEST_WORKER_H
#define C300X_REQUEST_WORKER_H

#include <poll.h>
#include <stddef.h>

#include "openwebnet_waiters.h"
#include "request_queue.h"

#define C300X_REQUEST_WORKER_FREE (-1)
#define C300X_REQUEST_WORKER_GONE (-2)

enum c300x_request_worker_turn {
    C300X_REQUEST_WORKER_MINE,
    C300X_REQUEST_WORKER_WAIT,
    C300X_REQUEST_WORKER_FULL,
    C300X_REQUEST_WORKER_LEFT, /* its caller left while it waited; it is not run */
};

/* One job of an API request beside the HTTP loop. The request stays in its
 * client slot, the loop offers it again, and its handler runs anew until the
 * job has a result. A thread exists only while a job runs. One request owns
 * the worker from its first job until it is answered; others wait in the
 * queue and get the worker in the order they arrived. */
struct c300x_request_worker {
    int wake[2];
    int running;
    pthread_t thread;
    int owner_fd; /* FREE, GONE: its request ended while the job still runs */
    int armed_fd;
    int deferred;
    int waited; /* the armed request got the worker after waiting for it */
    int reaped; /* offer the requests again: a result is there or the owner is done */
    size_t stack_bytes;
    struct c300x_request_queue *queue;
    void (*execute)(void *job);
    void *job;
};

int c300x_request_worker_init(struct c300x_request_worker *worker, struct c300x_request_queue *queue,
                              void (*execute)(void *job), void *job, size_t stack_bytes);
/* Reap first: this only closes the wake pipe. */
void c300x_request_worker_close(struct c300x_request_worker *worker);
/* Returns a poll timeout: 0 when a waiting request can be offered again, else -1. */
int c300x_request_worker_prepare(struct c300x_request_worker *worker, struct pollfd *fd);
static inline int c300x_request_worker_finished(const struct c300x_request_worker *worker, const struct pollfd *fd)
{
    return worker->running && fd->fd == worker->wake[0] && (fd->revents & POLLIN) != 0;
}
/* Block until the running job is done; the caller reaps it. */
static inline void c300x_request_worker_wait(const struct c300x_request_worker *worker)
{
    if (worker->running) {
        c300x_openwebnet_wait_readable(worker->wake[0]);
    }
}
/* Join the job. Zero when the request that started it has ended meanwhile. */
int c300x_request_worker_reap(struct c300x_request_worker *worker);
void c300x_request_worker_begin(struct c300x_request_worker *worker, int client_fd);
/* The handler has returned. deferred: the request runs again, on whichever
 * worker it waits for. Nonzero when it owned this worker and is done with it. */
int c300x_request_worker_end(struct c300x_request_worker *worker, int deferred);
/* Nonzero while another request has a job of this worker running or done. */
static inline int c300x_request_worker_owned_by_other(const struct c300x_request_worker *worker, int client_fd)
{
    return worker->owner_fd >= 0 && worker->owner_fd != client_fd;
}
/* The request of this client is over. Nonzero when it owned the worker. */
int c300x_request_worker_abandon(struct c300x_request_worker *worker, int client_fd);
/* Whose turn it is for the armed request; WAIT marks it deferred. */
enum c300x_request_worker_turn c300x_request_worker_turn(struct c300x_request_worker *worker);
/* Nonzero when the armed request waited, has the worker now, and its caller
 * has left. A caller that only closed its sending side counts as gone. */
int c300x_request_worker_caller_left(struct c300x_request_worker *worker);
/* Make the armed request the owner and start its job; zero without a thread. */
int c300x_request_worker_start(struct c300x_request_worker *worker);

#endif
