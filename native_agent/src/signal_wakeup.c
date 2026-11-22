#include "signal_wakeup.h"

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>

/* A detached thread can still be in its handler during shutdown. Retain one
 * CLOEXEC pipe until process exit rather than closing/reusing its descriptors. */
static int reader = -1;
static volatile sig_atomic_t writer = -1;

int c300x_signal_wakeup_init(void)
{
    if (reader < 0) {
        int pair[2];
        if (pipe(pair) != 0) {
            return -1;
        }
        for (int index = 0; index < 2; index++) {
            if (fcntl(pair[index], F_SETFD, FD_CLOEXEC) < 0
                || fcntl(pair[index], F_SETFL, O_NONBLOCK) < 0) {
                int error = errno;
                close(pair[0]);
                close(pair[1]);
                errno = error;
                return -1;
            }
        }
        reader = pair[0];
        writer = pair[1];
    }
    c300x_signal_wakeup_drain();
    return reader;
}

void c300x_signal_wakeup_drain(void)
{
    char pending[64];
    ssize_t count;
    do {
        count = read(reader, pending, sizeof(pending));
    } while (count > 0 || (count < 0 && errno == EINTR));
}

void c300x_signal_wakeup_notify(void)
{
    int saved_errno = errno;
    int fd = writer;
    if (fd >= 0) {
        while (write(fd, "x", 1) < 0 && errno == EINTR) {
        }
    }
    errno = saved_errno;
}
