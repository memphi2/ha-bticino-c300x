#ifndef C300X_OPENWEBNET_WAITERS_H
#define C300X_OPENWEBNET_WAITERS_H

#include "pthread_compat.h"

/* Requests that may wait for the worker; one more is answered openwebnet_busy
 * so that waiting requests never use up the API client slots. */
#define C300X_OPENWEBNET_MAX_WAITERS 3

struct c300x_openwebnet_waiters {
    int count;
    int fds[C300X_OPENWEBNET_MAX_WAITERS];
};

/* Nonzero when the client waits already or got a place; zero when all are taken. */
int c300x_openwebnet_waiters_add(struct c300x_openwebnet_waiters *waiters, int fd);
/* Nonzero when the client was waiting. */
int c300x_openwebnet_waiters_forget(struct c300x_openwebnet_waiters *waiters, int fd);
/* Nonzero when the peer of a request that sent everything has closed. */
int c300x_openwebnet_caller_left(int fd);
/* Start a joinable worker that no signal interrupts, with a fixed stack. */
int c300x_openwebnet_worker_start(pthread_t *thread, void *(*run)(void *), void *context);
/* A close-on-exec pipe, or both ends -1 and zero. */
int c300x_openwebnet_wake_pipe(int fds[2]);
/* Block until the descriptor is readable. */
void c300x_openwebnet_wait_readable(int fd);

#endif
