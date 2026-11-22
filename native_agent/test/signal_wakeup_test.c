#include "../src/signal_wakeup.h"

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <unistd.h>

int main(void)
{
    errno = EDOM;
    c300x_signal_wakeup_notify();
    assert(errno == EDOM);
    int fd = c300x_signal_wakeup_init();
    assert(fd >= 0);
    assert(fcntl(fd, F_GETFD) & FD_CLOEXEC);
    assert(fcntl(fd, F_GETFL) & O_NONBLOCK);
    struct pollfd event = {.fd = fd, .events = POLLIN};
    assert(poll(&event, 1, 0) == 0);
    errno = ERANGE;
    c300x_signal_wakeup_notify();
    assert(errno == ERANGE);
    assert(poll(&event, 1, 0) == 1);
    c300x_signal_wakeup_drain();
    assert(poll(&event, 1, 0) == 0);
    /* Saturation must remain nonblocking, with a readable notification. */
    for (int i = 0; i < 100000; i++) {
        c300x_signal_wakeup_notify();
    }
    assert(poll(&event, 1, 0) == 1);
    for (int i = 0; i < 1000; i++) {
        assert(c300x_signal_wakeup_init() == fd);
    }
    assert(poll(&event, 1, 0) == 0);
    return 0;
}
