/* Pause a completed scan before notifying the owning loop. Host tests only. */
#include <fcntl.h>
#include <sys/eventfd.h>
#include <unistd.h>

int __real_eventfd_write(int, eventfd_t);
int __wrap_eventfd_write(int fd, eventfd_t value)
{
    if (access("barrier/hold", F_OK) == 0) {
        int mark = open("barrier/ready", O_WRONLY | O_CREAT, 0600);
        if (mark >= 0) close(mark);
        for (int i = 0; i < 5000 && access("barrier/hold", F_OK) == 0; ++i) usleep(1000);
    }
    return __real_eventfd_write(fd, value);
}
