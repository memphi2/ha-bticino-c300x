#ifndef C300X_REQUEST_QUEUE_H
#define C300X_REQUEST_QUEUE_H

/* The API has six client slots. Each of the two workers holds one for the
 * request it runs, and the requests waiting for either worker share these
 * places, so one slot always stays free for a request that needs no worker. */
#define C300X_REQUEST_QUEUE_PLACES 3

/* Requests waiting for a worker, in the order they arrived. */
struct c300x_request_queue {
    int count;
    struct {
        int fd;
        const void *worker;
    } places[C300X_REQUEST_QUEUE_PLACES];
};

/* The longest waiting request of that worker, or -1. */
int c300x_request_queue_first(const struct c300x_request_queue *queue, const void *worker);
/* Nonzero when the request waits already or got a place; zero when all are taken. */
int c300x_request_queue_add(struct c300x_request_queue *queue, const void *worker, int fd);
/* Nonzero when the request was waiting. */
int c300x_request_queue_remove(struct c300x_request_queue *queue, const void *worker, int fd);

#endif
