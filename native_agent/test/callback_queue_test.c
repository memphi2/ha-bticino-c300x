#include "../src/callback_queue.h"
#include "../src/http_util.h"
#include <assert.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static int released;
static int entered;

int c300x_http_post_callback(const char *url, const char *token, const char *payload, int timeout)
{
    (void)url; (void)token; (void)payload; (void)timeout;
    pthread_mutex_lock(&lock);
    entered++;
    pthread_cond_broadcast(&changed);
    while (!released) {
        pthread_cond_wait(&changed, &lock);
    }
    pthread_mutex_unlock(&lock);
    return 1;
}

int c300x_https_post(const char *url, const char *header, const char *token, const char *payload,
    char *response, size_t capacity, int timeout, long *status, const char **error)
{
    (void)url; (void)header; (void)token; (void)payload; (void)response;
    (void)capacity; (void)timeout; (void)status; (void)error;
    assert(!"unexpected HTTPS request");
    return 0;
}

static struct c300x_callback_job *job(void)
{
    struct c300x_callback_job *result = calloc(1, sizeof(*result));
    assert(result != NULL);
    strcpy(result->url, "http://local.invalid/event");
    result->queued_at = c300x_system_metrics_monotonic_ms();
    result->timeout_ms = 100;
    return result;
}

int main(void)
{
    struct c300x_callback_queue *queue = c300x_callback_queue_create();
    assert(queue != NULL);
    long long start = c300x_system_metrics_monotonic_ms();
    for (int i = 0; i < C300X_CALLBACK_CAPACITY; i++) {
        assert(c300x_callback_queue_submit(queue, job()));
    }
    struct c300x_callback_job *overflow = job();
    assert(!c300x_callback_queue_submit(queue, overflow));
    free(overflow);
    assert(c300x_system_metrics_monotonic_ms() - start < 100);
    pthread_mutex_lock(&lock);
    while (!entered) {
        pthread_cond_wait(&changed, &lock);
    }
    assert(entered == 1);
    released = 1;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&lock);
    int completed = 0;
    while (completed < C300X_CALLBACK_CAPACITY) {
        struct pollfd pollfd = {.fd = c300x_callback_queue_fd(queue), .events = POLLIN};
        assert(poll(&pollfd, 1, 2000) == 1);
        struct c300x_callback_job *result;
        while ((result = c300x_callback_queue_take(queue)) != NULL) {
            assert(result->ok);
            completed++;
            free(result);
        }
    }
    c300x_callback_queue_close(queue);
    return 0;
}
