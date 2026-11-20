#include "openwebnet_async.h"

#include <errno.h>
#include <string.h>
#include <unistd.h>

/* The HTTP loop thread arms one instance around a request handler. */
static struct c300x_openwebnet_async *armed;
/* The instance whose worker a call on the loop thread has to wait for. */
static struct c300x_openwebnet_async *shared;

static void wait_for_worker(void);

#define OWNER_NONE (-1)
#define OWNER_GONE (-2)

static void *run_job(void *context)
{
    struct c300x_openwebnet_async *async = context;
    char done = 1;

    c300x_openwebnet_execute(&async->job);
    /* The loop reads the job only after this byte; a pipe of one byte per
     * job cannot be full. */
    while (write(async->wake[1], &done, 1) < 0 && errno == EINTR) {
    }
    return NULL;
}

static void store_result(struct c300x_openwebnet_async *async, const struct c300x_openwebnet_call *call, int used)
{
    async->used[async->result_count] = used;
    async->results[async->result_count++] = *call;
}

static int defer(struct c300x_openwebnet_async *async, struct c300x_openwebnet_call *call)
{
    async->deferred = 1;
    c300x_openwebnet_call_deferred = 1;
    call->ok = 0;
    call->error[0] = '\0';
    return 1;
}

static int hook(struct c300x_openwebnet_call *call)
{
    struct c300x_openwebnet_async *async = armed;

    if (async == NULL || async->armed_fd < 0) {
        return 0;
    }
    if (async->deferred) {
        return defer(async, call);
    }
    if (async->owner_fd != OWNER_NONE && async->owner_fd != async->armed_fd) {
        if (!c300x_openwebnet_waiters_add(&async->waiters, async->armed_fd)) {
            return c300x_openwebnet_call_fail(call, "openwebnet_busy");
        }
        async->waiting = 1;
        return defer(async, call);
    }
    for (int index = 0; index < async->result_count; index++) {
        if (!async->used[index] && c300x_openwebnet_call_same(&async->results[index], call)) {
            async->used[index] = 1;
            c300x_openwebnet_call_copy_result(call, &async->results[index]);
            return 1;
        }
    }
    if (async->running) {
        return defer(async, call);
    }
    if (c300x_openwebnet_waiters_forget(&async->waiters, async->armed_fd)
            && c300x_openwebnet_caller_left(async->armed_fd)) {
        /* Nobody waits for it any more: a door must not open that late. */
        return c300x_openwebnet_call_fail(call, "client_gone");
    }
    async->owner_fd = async->armed_fd;
    if (async->result_count == C300X_OPENWEBNET_ASYNC_RESULTS) {
        /* No room to remember another result: run it here, as before. */
        return 0;
    }
    async->job = *call;
    if (!c300x_openwebnet_worker_start(&async->thread, run_job, async)) {
        /* No thread: run it here, and remember it so a later pass of this
         * request does not send the command again. */
        c300x_openwebnet_execute(call);
        store_result(async, call, 1);
        return 1;
    }
    async->running = 1;
    return defer(async, call);
}

int c300x_openwebnet_async_init(struct c300x_openwebnet_async *async)
{
    memset(async, 0, sizeof(*async));
    async->owner_fd = OWNER_NONE;
    async->armed_fd = -1;
    if (!c300x_openwebnet_wake_pipe(async->wake)) {
        return 0;
    }
    shared = async;
    c300x_openwebnet_before_inline = wait_for_worker;
    return 1;
}

static void reap(struct c300x_openwebnet_async *async)
{
    char done;

    /* After the wake byte this only waits for the thread to leave; before it,
     * for the rest of the exchange, which the bus timeouts bound. */
    (void)pthread_join(async->thread, NULL);
    while (read(async->wake[0], &done, 1) < 0 && errno == EINTR) {
    }
    async->running = 0;
    if (async->owner_fd == OWNER_GONE) {
        async->owner_fd = OWNER_NONE;
        async->result_count = 0;
        return;
    }
    store_result(async, &async->job, 0);
}

static void wait_for_worker(void)
{
    if (shared != NULL && shared->running) {
        c300x_openwebnet_wait_readable(shared->wake[0]);
    }
}

void c300x_openwebnet_async_abandon(struct c300x_openwebnet_async *async, int client_fd)
{
    (void)c300x_openwebnet_waiters_forget(&async->waiters, client_fd);
    if (async->owner_fd == client_fd) {
        async->owner_fd = async->running ? OWNER_GONE : OWNER_NONE;
        async->result_count = 0;
    }
}

void c300x_openwebnet_async_close(struct c300x_openwebnet_async *async)
{
    if (async->running) {
        /* A command on its way is finished, never cut off: a lock that was
         * pressed is released. */
        reap(async);
    }
    for (int index = 0; index < 2; index++) {
        if (async->wake[index] >= 0) {
            close(async->wake[index]);
            async->wake[index] = -1;
        }
    }
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
    *fd = (struct pollfd){.fd = async->running ? async->wake[0] : -1, .events = POLLIN};
    if (async->waiting && async->owner_fd == OWNER_NONE) {
        async->waiting = 0;
        return 0;
    }
    return -1;
}

void c300x_openwebnet_async_tick(struct c300x_openwebnet_async *async, const struct pollfd *fd)
{
    if (async->running && fd->fd == async->wake[0] && (fd->revents & POLLIN) != 0) {
        reap(async);
    }
}

void c300x_openwebnet_async_begin(struct c300x_openwebnet_async *async, int client_fd)
{
    if (async->wake[0] < 0) {
        return;
    }
    async->armed_fd = client_fd;
    async->deferred = 0;
    c300x_openwebnet_call_deferred = 0;
    if (async->owner_fd == client_fd) {
        memset(async->used, 0, sizeof(async->used));
    }
    armed = async;
    c300x_openwebnet_hook = hook;
}

int c300x_openwebnet_async_end(struct c300x_openwebnet_async *async)
{
    int deferred = async->deferred;

    if (async->armed_fd < 0) {
        return 0;
    }
    if (!deferred) {
        /* Answered. A call it no longer waits for still runs to its end. */
        c300x_openwebnet_async_abandon(async, async->armed_fd);
    }
    async->armed_fd = -1;
    async->deferred = 0;
    c300x_openwebnet_call_deferred = 0;
    armed = NULL;
    c300x_openwebnet_hook = NULL;
    return deferred;
}
