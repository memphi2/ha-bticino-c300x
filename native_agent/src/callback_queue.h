#ifndef C300X_CALLBACK_QUEUE_H
#define C300X_CALLBACK_QUEUE_H

#include "c300x_agent.h"
#include "system_metrics.h"

#define C300X_CALLBACK_CAPACITY 8

struct c300x_callback_job {
    void (*perform)(struct c300x_callback_job *job);
    char *response;
    size_t response_len;
    char url[512];
    char token[C300X_MAX_TOKEN_LEN];
    char subscription_id[48];
    char event_type[64];
    char payload[8192];
    unsigned long generation;
    int timeout_ms;
    long long queued_at;
    int has_metrics;
    struct system_metrics_sample metrics;
    int ok;
    long http_status;
    const char *error;
};

struct c300x_callback_queue;
struct c300x_callback_queue *c300x_callback_queue_create(void);
int c300x_callback_queue_fd(const struct c300x_callback_queue *queue);
/* Ownership transfers only on successful submission. */
int c300x_callback_queue_submit(struct c300x_callback_queue *queue, struct c300x_callback_job *job);
struct c300x_callback_job *c300x_callback_queue_take(struct c300x_callback_queue *queue);
void c300x_callback_queue_discard_pending(struct c300x_callback_queue *queue);
void c300x_callback_queue_close(struct c300x_callback_queue *queue);
void c300x_callback_job_free(struct c300x_callback_job *job);

#endif
