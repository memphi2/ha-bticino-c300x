#include "callback_queue.h"
#include "http_callback.h"
#include "http_util.h"
#include "https_client.h"
#include "pthread_compat.h"
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct c300x_callback_queue {
    pthread_mutex_t lock;
    pthread_cond_t changed;
    int notify[2];
    int stopped;
    int outstanding;
    int pending_count;
    int done_count;
    struct c300x_callback_job *pending[C300X_CALLBACK_CAPACITY];
    struct c300x_callback_job *done[C300X_CALLBACK_CAPACITY];
};

static void post(struct c300x_callback_job *job)
{
    if (c300x_system_metrics_monotonic_ms() - job->queued_at > 30000) {
        job->error = "callback_expired";
        return;
    }
    if (strncmp(job->url, "https://", 8) == 0) {
        job->ok = c300x_https_post(job->url, C300X_EVENT_TOKEN_HEADER, job->token,
            job->payload, NULL, 0, job->timeout_ms, &job->http_status, &job->error);
    } else {
        job->ok = c300x_http_post_callback(job->url, job->token, job->payload, job->timeout_ms);
        job->error = job->ok ? NULL : "http_callback_failed";
    }
}

static void *worker(void *context)
{
    struct c300x_callback_queue *queue = context;
    for (;;) {
        pthread_mutex_lock(&queue->lock);
        while (!queue->stopped && !queue->pending_count) {
            pthread_cond_wait(&queue->changed, &queue->lock);
        }
        if (queue->stopped) {
            pthread_mutex_unlock(&queue->lock);
            break;
        }
        struct c300x_callback_job *job = queue->pending[0];
        queue->pending_count--;
        memmove(queue->pending, queue->pending + 1, (size_t)queue->pending_count * sizeof(job));
        pthread_mutex_unlock(&queue->lock);
        post(job);
        pthread_mutex_lock(&queue->lock);
        if (queue->stopped) {
            free(job);
        } else {
            queue->done[queue->done_count++] = job;
            ssize_t written;
            do {
                written = write(queue->notify[1], "x", 1);
            } while (written < 0 && errno == EINTR);
        }
        pthread_mutex_unlock(&queue->lock);
    }
    pthread_cond_destroy(&queue->changed);
    pthread_mutex_destroy(&queue->lock);
    free(queue);
    return NULL;
}

struct c300x_callback_queue *c300x_callback_queue_create(void)
{
    struct c300x_callback_queue *queue = calloc(1, sizeof(*queue));
    if (queue == NULL) {
        return NULL;
    }
    if (pthread_mutex_init(&queue->lock, NULL) != 0) {
        free(queue);
        return NULL;
    }
    if (pthread_cond_init(&queue->changed, NULL) != 0) {
        pthread_mutex_destroy(&queue->lock);
        free(queue);
        return NULL;
    }
    if (pipe(queue->notify) != 0) {
        goto failed;
    }
    set_fd_cloexec(queue->notify[0]);
    set_fd_cloexec(queue->notify[1]);
    set_fd_nonblocking(queue->notify[0]);
    set_fd_nonblocking(queue->notify[1]);
    pthread_t thread;
    pthread_attr_t attr;
    int status = pthread_attr_init(&attr);
    if (!status) {
        status = pthread_attr_setstacksize(&attr, 256 * 1024);
        if (!status) {
            status = pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
        }
        if (!status) {
            status = pthread_create(&thread, &attr, worker, queue);
        }
        pthread_attr_destroy(&attr);
    }
    if (!status) {
        return queue;
    }
    close(queue->notify[0]);
    close(queue->notify[1]);
failed:
    pthread_cond_destroy(&queue->changed);
    pthread_mutex_destroy(&queue->lock);
    free(queue);
    return NULL;
}

int c300x_callback_queue_fd(const struct c300x_callback_queue *queue)
{
    return queue == NULL ? -1 : queue->notify[0];
}

int c300x_callback_queue_submit(struct c300x_callback_queue *queue, struct c300x_callback_job *job)
{
    if (queue == NULL) {
        return 0;
    }
    pthread_mutex_lock(&queue->lock);
    if (queue->stopped || queue->outstanding == C300X_CALLBACK_CAPACITY) {
        pthread_mutex_unlock(&queue->lock);
        return 0;
    }
    queue->pending[queue->pending_count++] = job;
    queue->outstanding++;
    pthread_cond_signal(&queue->changed);
    pthread_mutex_unlock(&queue->lock);
    return 1;
}

struct c300x_callback_job *c300x_callback_queue_take(struct c300x_callback_queue *queue)
{
    if (queue == NULL) {
        return NULL;
    }
    pthread_mutex_lock(&queue->lock);
    struct c300x_callback_job *job = NULL;
    if (queue->done_count) {
        job = queue->done[0];
        queue->done_count--;
        queue->outstanding--;
        memmove(queue->done, queue->done + 1, (size_t)queue->done_count * sizeof(job));
        char byte;
        ssize_t received;
        do {
            received = read(queue->notify[0], &byte, 1);
        } while (received < 0 && errno == EINTR);
    }
    pthread_mutex_unlock(&queue->lock);
    return job;
}

static void discard_pending_locked(struct c300x_callback_queue *queue)
{
    while (queue->pending_count) {
        free(queue->pending[--queue->pending_count]);
        queue->outstanding--;
    }
}

void c300x_callback_queue_discard_pending(struct c300x_callback_queue *queue)
{
    if (queue != NULL) {
        pthread_mutex_lock(&queue->lock);
        discard_pending_locked(queue);
        pthread_mutex_unlock(&queue->lock);
    }
}

void c300x_callback_queue_close(struct c300x_callback_queue *queue)
{
    if (queue == NULL) {
        return;
    }
    pthread_mutex_lock(&queue->lock);
    queue->stopped = 1;
    discard_pending_locked(queue);
    while (queue->done_count) {
        free(queue->done[--queue->done_count]);
    }
    close(queue->notify[0]);
    close(queue->notify[1]);
    pthread_cond_signal(&queue->changed);
    pthread_mutex_unlock(&queue->lock);
    /* The detached worker owns its remaining request and queue until it exits.
       Shutdown must not wait for a platform DNS resolver; it never owns runtime. */
}
