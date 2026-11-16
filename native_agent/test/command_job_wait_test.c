#include "../src/command_job.h"

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

static long long now = 100;
long long c300x_monotonic_ms(void) { return now; }

int main(int argc, char **argv)
{
    struct c300x_command_job job;
    struct pollfd fd;
    assert(argc == 3);
    c300x_command_job_init(&job);
    char *missing[] = {"/missing-c300x-test", NULL};
    assert(!c300x_command_job_start_wait(&job, missing[0], missing));
    assert(c300x_command_job_prepare(&job, &fd) == -1 && fd.fd == -1);
    int socket_fd = socket(AF_INET, SOCK_STREAM, 0);
    assert(socket_fd >= 0);
    int high_fd = fcntl(socket_fd, F_DUPFD, 512);
    assert(high_fd >= 512);
    char *command[] = {argv[1], argv[2], NULL};
    assert(c300x_command_job_start_wait(&job, argv[1], command));
    pid_t child = job.pid;
    assert(!c300x_command_job_start_wait(&job, argv[1], command));
    assert(job.pid == child && job.deadline_ms == 0);
    now += 1000000000;
    for (int i = 0; i < 20; i++) {
        int wait = c300x_command_job_prepare(&job, &fd);
        assert(wait == 50);
        (void)poll(&fd, 1, 5);
        c300x_command_job_tick(&job);
        assert(job.pid == child && !job.complete && !job.failed && job.used == 0);
    }
    if (strcmp(argv[2], "cancel") == 0) {
        c300x_command_job_close(&job);
        int status;
        pid_t result = waitpid(child, &status, 0);
        assert(result == child || (result == -1 && errno == ECHILD));
        if (result == child) {
            assert(WIFSIGNALED(status));
        }
    } else {
        int release = open("release", O_CREAT | O_WRONLY, 0600);
        assert(release >= 0);
        close(release);
        for (int i = 0; job.pid > 0 && i < 100; i++) {
            (void)c300x_command_job_prepare(&job, &fd);
            (void)poll(&fd, 1, 10);
            c300x_command_job_tick(&job);
        }
        assert(job.pid == 0 && job.complete);
        assert(job.failed == (strcmp(argv[2], "fail") == 0));
    }
    close(high_fd);
    close(socket_fd);
    return 0;
}
