#include "openwebnet_waiters.h"

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>
#include <unistd.h>

static int waiter_index(const struct c300x_openwebnet_waiters *waiters, int fd)
{
    for (int index = 0; index < waiters->count; index++) {
        if (waiters->fds[index] == fd) {
            return index;
        }
    }
    return -1;
}

int c300x_openwebnet_waiters_add(struct c300x_openwebnet_waiters *waiters, int fd)
{
    if (waiter_index(waiters, fd) >= 0) {
        return 1;
    }
    if (waiters->count == C300X_OPENWEBNET_MAX_WAITERS) {
        return 0;
    }
    waiters->fds[waiters->count++] = fd;
    return 1;
}

int c300x_openwebnet_waiters_forget(struct c300x_openwebnet_waiters *waiters, int fd)
{
    int index = waiter_index(waiters, fd);

    if (index < 0) {
        return 0;
    }
    waiters->fds[index] = waiters->fds[--waiters->count];
    return 1;
}

int c300x_openwebnet_caller_left(int fd)
{
    char byte;
    ssize_t count = recv(fd, &byte, 1, MSG_PEEK | MSG_DONTWAIT);

    return count == 0 || (count < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR);
}

int c300x_openwebnet_worker_start(pthread_t *thread, void *(*run)(void *), void *context, size_t stack_bytes)
{
    pthread_attr_t attr;
    sigset_t all, previous;
    int status = pthread_attr_init(&attr);

    if (status != 0) {
        return 0;
    }
    /* A signal must not end a blocking bus read between press and release. */
    sigfillset(&all);
    pthread_sigmask(SIG_BLOCK, &all, &previous);
    status = pthread_attr_setstacksize(&attr, stack_bytes);
    if (status == 0) {
        status = pthread_create(thread, &attr, run, context);
    }
    pthread_sigmask(SIG_SETMASK, &previous, NULL);
    pthread_attr_destroy(&attr);
    return status == 0;
}

int c300x_openwebnet_wake_pipe(int fds[2])
{
    if (pipe(fds) != 0) {
        fds[0] = -1;
        fds[1] = -1;
        return 0;
    }
    (void)fcntl(fds[0], F_SETFD, FD_CLOEXEC);
    (void)fcntl(fds[1], F_SETFD, FD_CLOEXEC);
    return 1;
}

void c300x_openwebnet_wait_readable(int fd)
{
    struct pollfd wait = {.fd = fd, .events = POLLIN};

    while (poll(&wait, 1, -1) < 0 && errno == EINTR) {
    }
}
