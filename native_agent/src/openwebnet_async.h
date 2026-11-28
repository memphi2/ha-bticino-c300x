#ifndef C300X_OPENWEBNET_ASYNC_H
#define C300X_OPENWEBNET_ASYNC_H

#include "openwebnet_call.h"

#include "request_worker.h"

#include <poll.h>

#define C300X_OPENWEBNET_ASYNC_RESULTS 8

/* Keeps OpenWebNet exchanges of API requests off the HTTP loop.
 *
 * A request handler calls the OpenWebNet client as before. Between begin and
 * end, a call that has no result yet is started on a worker thread, which
 * exists only while a call runs, and the handler is told to return at once.
 * The request stays in its client slot and is handled again when the worker
 * is done; the handler then gets the stored result from the same call. A
 * request owns the worker from its first call until it is answered, so other
 * requests with OpenWebNet calls wait, in the order they arrived. A request
 * that waited is not started when its caller has left meanwhile.
 *
 * A handler runs several times. What it checks before its first call it must
 * not check again once the request owns the worker (async_owns): the command
 * may be out already, and the answer has to be the one for that command. */
struct c300x_openwebnet_async {
    struct c300x_request_worker worker;
    const char *refusal;
    int result_count;
    int used[C300X_OPENWEBNET_ASYNC_RESULTS];
    struct c300x_openwebnet_call results[C300X_OPENWEBNET_ASYNC_RESULTS];
    struct c300x_openwebnet_call job;
};

int c300x_openwebnet_async_init(struct c300x_openwebnet_async *async, struct c300x_request_queue *queue);
void c300x_openwebnet_async_close(struct c300x_openwebnet_async *async);
/* Returns a poll timeout: 0 when a waiting request can be offered again, else -1. */
int c300x_openwebnet_async_prepare(struct c300x_openwebnet_async *async, struct pollfd *fd);
void c300x_openwebnet_async_tick(struct c300x_openwebnet_async *async, const struct pollfd *fd);
void c300x_openwebnet_async_begin(struct c300x_openwebnet_async *async, int client_fd);
/* Nonzero while the armed request has a call running or done. */
int c300x_openwebnet_async_owns(const struct c300x_openwebnet_async *async);
/* Nonzero after the handler: a call left the request unanswered. */
int c300x_openwebnet_async_deferred(const struct c300x_openwebnet_async *async);
/* After the handler: an error name when its command was not sent at all and
 * the request is to be answered with it, else NULL. */
const char *c300x_openwebnet_async_refusal(const struct c300x_openwebnet_async *async);
/* In the handler, after a call that was refused: the handler answers the
 * request itself, without that call, and nothing waits. Zero when there
 * was no refusal. */
int c300x_openwebnet_async_drop_refusal(struct c300x_openwebnet_async *async);
/* deferred: the request runs again, here or for the media worker. */
void c300x_openwebnet_async_end(struct c300x_openwebnet_async *async, int deferred);
/* The request of this client is over, however it ended. */
void c300x_openwebnet_async_abandon(struct c300x_openwebnet_async *async, int client_fd);
#endif
