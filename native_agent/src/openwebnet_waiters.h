#ifndef C300X_OPENWEBNET_WAITERS_H
#define C300X_OPENWEBNET_WAITERS_H

#include <stddef.h>

#include "pthread_compat.h"
#include "request_queue.h"

/* Take the place of one waiting request whose caller has left; zero when all wait still. */
int c300x_request_queue_drop_departed(struct c300x_request_queue *queue);
/* Nonzero when the peer of a request that sent everything has closed. */
int c300x_openwebnet_caller_left(int fd);
/* Start a joinable worker that no signal interrupts, with a stack of that size. */
int c300x_openwebnet_worker_start(pthread_t *thread, void *(*run)(void *), void *context, size_t stack_bytes);
/* A close-on-exec pipe, or both ends -1 and zero. */
int c300x_openwebnet_wake_pipe(int fds[2]);
/* Block until the descriptor is readable. */
void c300x_openwebnet_wait_readable(int fd);

#endif
