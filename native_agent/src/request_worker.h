#ifndef C300X_REQUEST_WORKER_H
#define C300X_REQUEST_WORKER_H

#include <poll.h>
#include <stddef.h>

#include "openwebnet_waiters.h"

#define C300X_REQUEST_WORKER_FREE (-1)
#define C300X_REQUEST_WORKER_GONE (-2)

enum c300x_request_worker_turn {
    C300X_REQUEST_WORKER_MINE,
    C300X_REQUEST_WORKER_WAIT,
    C300X_REQUEST_WORKER_FULL,
};

/* One job of an API request beside the HTTP loop. The request stays in its
 * client slot, the loop offers it again, and its handler runs anew until the
 * job has a result. A thread exists only while a job runs. One request owns
 * the worker from its first job until it is answered; others wait, a bounded
 * number of them, in the order the loop offers them. */
struct c300x_request_worker {
    int wake[2];
    int running;
    pthread_t thread;
    int owner_fd; /* FREE, GONE: its request ended while the job still runs */
    int armed_fd;
    int deferred;
    int waiting;
    int reaped; /* offer the requests again: one of them has its result now */
    size_t stack_bytes;
    struct c300x_openwebnet_waiters waiters;
    void (*execute)(void *job);
    void *job;
};

int c300x_request_worker_init(struct c300x_request_worker *worker, void (*execute)(void *job), void *job,
                              size_t stack_bytes);
/* Reap first: this only closes the wake pipe. */
void c300x_request_worker_close(struct c300x_request_worker *worker);
/* Returns a poll timeout: 0 when a waiting request can be offered again, else -1. */
int c300x_request_worker_prepare(struct c300x_request_worker *worker, struct pollfd *fd);
int c300x_request_worker_finished(const struct c300x_request_worker *worker, const struct pollfd *fd);
/* Block until the running job is done; the caller reaps it. */
void c300x_request_worker_wait(const struct c300x_request_worker *worker);
/* Join the job. Zero when the request that started it has ended meanwhile. */
int c300x_request_worker_reap(struct c300x_request_worker *worker);
void c300x_request_worker_begin(struct c300x_request_worker *worker, int client_fd);
/* Nonzero: the request is deferred. *answered is set when it was the owner and is done. */
int c300x_request_worker_end(struct c300x_request_worker *worker, int *answered);
/* The request of this client is over. Nonzero when it owned the worker. */
int c300x_request_worker_abandon(struct c300x_request_worker *worker, int client_fd);
/* Whose turn it is for the armed request; WAIT marks it deferred. */
enum c300x_request_worker_turn c300x_request_worker_turn(struct c300x_request_worker *worker);
/* Nonzero when the armed request waited its turn and its caller has left. */
int c300x_request_worker_caller_left(struct c300x_request_worker *worker);
/* Make the armed request the owner and start its job; zero without a thread. */
int c300x_request_worker_start(struct c300x_request_worker *worker);

#endif
