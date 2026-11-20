#include "openwebnet_async.h"

#include <string.h>

/* The HTTP loop thread arms one instance around a request handler. */
static struct c300x_openwebnet_async *armed;
/* The instance whose worker a call on the loop thread has to wait for. */
static struct c300x_openwebnet_async *shared;

static void run_job(void *job)
{
    c300x_openwebnet_execute(job);
}

static void store_result(struct c300x_openwebnet_async *async, const struct c300x_openwebnet_call *call, int used)
{
    async->used[async->result_count] = used;
    async->results[async->result_count++] = *call;
}

static int defer(struct c300x_openwebnet_async *async, struct c300x_openwebnet_call *call)
{
    async->worker.deferred = 1;
    c300x_openwebnet_call_deferred = 1;
    call->ok = 0;
    call->error[0] = '\0';
    return 1;
}

/* The command is not sent. The handler returns as for a deferred call, with
 * no effect, and the request is answered with the error. */
static int refuse(struct c300x_openwebnet_async *async, struct c300x_openwebnet_call *call, const char *error)
{
    async->refusal = error;
    return defer(async, call);
}

static int hook(struct c300x_openwebnet_call *call)
{
    struct c300x_openwebnet_async *async = armed;
    struct c300x_request_worker *worker;

    if (async == NULL || async->worker.armed_fd < 0) {
        return 0;
    }
    worker = &async->worker;
    if (worker->deferred) {
        return defer(async, call);
    }
    switch (c300x_request_worker_turn(worker)) {
    case C300X_REQUEST_WORKER_FULL:
        return refuse(async, call, "openwebnet_busy");
    case C300X_REQUEST_WORKER_WAIT:
        return defer(async, call);
    case C300X_REQUEST_WORKER_MINE:
        break;
    }
    for (int index = 0; index < async->result_count; index++) {
        if (!async->used[index] && c300x_openwebnet_call_same(&async->results[index], call)) {
            async->used[index] = 1;
            c300x_openwebnet_call_copy_result(call, &async->results[index]);
            return 1;
        }
    }
    if (worker->running) {
        return defer(async, call);
    }
    if (c300x_request_worker_caller_left(worker)) {
        /* Nobody waits for it any more: a door must not open that late. */
        return refuse(async, call, "client_gone");
    }
    if (async->result_count == C300X_OPENWEBNET_ASYNC_RESULTS) {
        /* No room to remember another result: run it here, as before. */
        worker->owner_fd = worker->armed_fd;
        return 0;
    }
    async->job = *call;
    if (!c300x_request_worker_start(worker)) {
        /* No thread: run it here, and remember it so a later pass of this
         * request does not send the command again. */
        c300x_openwebnet_execute(call);
        store_result(async, call, 1);
        return 1;
    }
    return defer(async, call);
}

static void reap(struct c300x_openwebnet_async *async)
{
    if (c300x_request_worker_reap(&async->worker)) {
        store_result(async, &async->job, 0);
    } else {
        async->result_count = 0;
    }
}

static void wait_for_worker(void)
{
    if (shared != NULL) {
        c300x_request_worker_wait(&shared->worker);
    }
}

int c300x_openwebnet_async_init(struct c300x_openwebnet_async *async, struct c300x_request_queue *queue)
{
    memset(async, 0, sizeof(*async));
    if (!c300x_request_worker_init(&async->worker, queue, run_job, &async->job, 256 * 1024)) {
        return 0;
    }
    shared = async;
    c300x_openwebnet_before_inline = wait_for_worker;
    return 1;
}

void c300x_openwebnet_async_abandon(struct c300x_openwebnet_async *async, int client_fd)
{
    if (c300x_request_worker_abandon(&async->worker, client_fd)) {
        async->result_count = 0;
    }
}

void c300x_openwebnet_async_close(struct c300x_openwebnet_async *async)
{
    if (async->worker.running) {
        /* A command on its way is finished, never cut off: a lock that was
         * pressed is released. The bus timeouts bound the wait. */
        reap(async);
    }
    c300x_request_worker_close(&async->worker);
    if (armed == async) {
        armed = NULL;
        c300x_openwebnet_hook = NULL;
    }
    if (shared == async) {
        shared = NULL;
        c300x_openwebnet_before_inline = NULL;
    }
}

int c300x_openwebnet_async_prepare(struct c300x_openwebnet_async *async, struct pollfd *fd)
{
    return c300x_request_worker_prepare(&async->worker, fd);
}

void c300x_openwebnet_async_tick(struct c300x_openwebnet_async *async, const struct pollfd *fd)
{
    if (c300x_request_worker_finished(&async->worker, fd)) {
        reap(async);
    }
}

void c300x_openwebnet_async_begin(struct c300x_openwebnet_async *async, int client_fd)
{
    c300x_request_worker_begin(&async->worker, client_fd);
    if (async->worker.armed_fd < 0) {
        return;
    }
    c300x_openwebnet_call_deferred = 0;
    async->refusal = NULL;
    if (async->worker.owner_fd == client_fd) {
        memset(async->used, 0, sizeof(async->used));
    }
    armed = async;
    c300x_openwebnet_hook = hook;
}

int c300x_openwebnet_async_owns(const struct c300x_openwebnet_async *async)
{
    return async->worker.armed_fd >= 0 && async->worker.owner_fd == async->worker.armed_fd;
}

int c300x_openwebnet_async_deferred(const struct c300x_openwebnet_async *async)
{
    return async->worker.deferred;
}

const char *c300x_openwebnet_async_refusal(const struct c300x_openwebnet_async *async)
{
    return async->refusal;
}

void c300x_openwebnet_async_end(struct c300x_openwebnet_async *async, int deferred)
{
    if (c300x_request_worker_end(&async->worker, deferred)) {
        async->result_count = 0;
    }
    async->refusal = NULL;
    c300x_openwebnet_call_deferred = 0;
    armed = NULL;
    c300x_openwebnet_hook = NULL;
}
