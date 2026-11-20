#include "request_queue.h"

static int find(const struct c300x_request_queue *queue, const void *worker, int fd)
{
    for (int index = 0; index < queue->count; index++) {
        if (queue->places[index].worker == worker && queue->places[index].fd == fd) {
            return index;
        }
    }
    return -1;
}

int c300x_request_queue_first(const struct c300x_request_queue *queue, const void *worker)
{
    for (int index = 0; index < queue->count; index++) {
        if (queue->places[index].worker == worker) {
            return queue->places[index].fd;
        }
    }
    return -1;
}

int c300x_request_queue_add(struct c300x_request_queue *queue, const void *worker, int fd)
{
    if (find(queue, worker, fd) >= 0) {
        return 1;
    }
    if (queue->count == C300X_REQUEST_QUEUE_PLACES) {
        return 0;
    }
    queue->places[queue->count].fd = fd;
    queue->places[queue->count++].worker = worker;
    return 1;
}

int c300x_request_queue_remove(struct c300x_request_queue *queue, const void *worker, int fd)
{
    int index = find(queue, worker, fd);

    if (index < 0) {
        return 0;
    }
    for (queue->count--; index < queue->count; index++) {
        queue->places[index] = queue->places[index + 1];
    }
    return 1;
}
