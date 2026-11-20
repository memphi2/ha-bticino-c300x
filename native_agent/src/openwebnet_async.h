#ifndef C300X_OPENWEBNET_ASYNC_H
#define C300X_OPENWEBNET_ASYNC_H

#include "openwebnet_call.h"

#include <poll.h>
#include <pthread.h>

#define C300X_OPENWEBNET_ASYNC_RESULTS 8

/* Keeps OpenWebNet exchanges of API requests off the HTTP loop.
 *
 * A request handler calls the OpenWebNet client as before. Between begin and
 * end, a call that has no result yet is started on a worker thread, which
 * exists only while a call runs, and the handler is told to return at once.
 * The request stays in its client slot and is handled again when the worker
 * is done; the handler then gets the stored result from the same call. A
 * request owns the worker from its first call until it is answered, so other
 * requests with OpenWebNet calls wait, in the order the loop offers them. */
struct c300x_openwebnet_async {
    int wake[2];
    int running;
    int finished;
    pthread_t thread;
    int owner_fd; /* -1: free, -2: its request ended while a call still runs */
    int armed_fd;
    int deferred;
    int waiting;
    int result_count;
    int used[C300X_OPENWEBNET_ASYNC_RESULTS];
    struct c300x_openwebnet_call results[C300X_OPENWEBNET_ASYNC_RESULTS];
    struct c300x_openwebnet_call job;
};

int c300x_openwebnet_async_init(struct c300x_openwebnet_async *async);
void c300x_openwebnet_async_close(struct c300x_openwebnet_async *async);
/* Returns a poll timeout: 0 when a waiting request can be offered again, else -1. */
int c300x_openwebnet_async_prepare(struct c300x_openwebnet_async *async, struct pollfd *fd);
void c300x_openwebnet_async_tick(struct c300x_openwebnet_async *async, const struct pollfd *fd);
void c300x_openwebnet_async_begin(struct c300x_openwebnet_async *async, int client_fd);
/* Nonzero: the request is deferred; nothing was answered and it runs again. */
int c300x_openwebnet_async_end(struct c300x_openwebnet_async *async);
#endif
