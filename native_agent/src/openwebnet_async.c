#include "openwebnet_async.h"

#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>

/* The HTTP loop thread arms one instance around a request handler. */
static struct c300x_openwebnet_async *armed;

#define OWNER_NONE (-1)
#define OWNER_GONE (-2)

static int same_call(const struct c300x_openwebnet_call *left, const struct c300x_openwebnet_call *right)
{
    return left->kind == right->kind && left->port == right->port
        && left->timeout_ms == right->timeout_ms && left->delay_ms == right->delay_ms
        && strcmp(left->host, right->host) == 0 && strcmp(left->first, right->first) == 0
        && strcmp(left->second, right->second) == 0;
}

static void copy_result(struct c300x_openwebnet_call *call, const struct c300x_openwebnet_call *result)
{
    call->ok = result->ok;
    memcpy(call->reply, result->reply, sizeof(call->reply));
    memcpy(call->readback, result->readback, sizeof(call->readback));
    memcpy(call->error, result->error, sizeof(call->error));
}

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
        async->waiting = 1;
        return defer(async, call);
    }
    for (int index = 0; index < async->result_count; index++) {
        if (!async->used[index] && same_call(&async->results[index], call)) {
            async->used[index] = 1;
            copy_result(call, &async->results[index]);
            return 1;
        }
    }
    if (async->running) {
        return defer(async, call);
    }
    async->owner_fd = async->armed_fd;
    if (async->result_count == C300X_OPENWEBNET_ASYNC_RESULTS) {
        /* No room to remember another result: run it here, as before. */
        return 0;
    }
    async->job = *call;
    if (pthread_create(&async->thread, NULL, run_job, async) != 0) {
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
    async->wake[0] = -1;
    async->wake[1] = -1;
    if (pipe(async->wake) != 0) {
        async->wake[0] = -1;
        async->wake[1] = -1;
        return 0;
    }
    for (int index = 0; index < 2; index++) {
        (void)fcntl(async->wake[index], F_SETFD, FD_CLOEXEC);
    }
    return 1;
}

static void reap(struct c300x_openwebnet_async *async)
{
    char done;

    /* The worker's last act is the wake byte, so this join does not wait for
     * the exchange, only for the thread to leave. */
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
    if (!deferred && async->owner_fd == async->armed_fd) {
        /* Answered. A call it no longer waits for still runs to its end. */
        async->owner_fd = async->running ? OWNER_GONE : OWNER_NONE;
        async->result_count = 0;
    }
    async->armed_fd = -1;
    async->deferred = 0;
    c300x_openwebnet_call_deferred = 0;
    armed = NULL;
    c300x_openwebnet_hook = NULL;
    return deferred;
}
