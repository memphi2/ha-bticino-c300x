/* A script the agent starts must not inherit the agent's open sockets. */
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include "../src/command_job.h"

void set_fd_nonblocking(int fd)
{
    int flags = fcntl(fd, F_GETFL, 0);
    assert(flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0);
}

long long c300x_monotonic_ms(void)
{
    static long long now;
    return now += 10;
}

int main(int argc, char **argv)
{
    char out[256];
    int exit_code = -1;
    struct c300x_command_job job;
    assert(argc == 2);
    /* Stands for a listening media socket, opened without close-on-exec. */
    int listener = socket(AF_INET, SOCK_STREAM, 0);
    assert(listener > 2);

    assert(c300x_command_capture(argv[1], "list", out, sizeof(out), 2000, &exit_code));
    assert(exit_code == 0);
    assert(strstr(out, "/dev/null") != NULL);
    assert(strstr(out, "socket:") == NULL);

    c300x_command_job_init(&job);
    assert(c300x_command_job_start(&job, argv[1], "list", 0, 100000));
    while (!job.complete) {
        usleep(10000);
        c300x_command_job_tick(&job);
    }
    assert(!job.failed);
    assert(strstr(job.output, "/dev/null") != NULL);
    assert(strstr(job.output, "socket:") == NULL);
    close(listener);
    return 0;
}
