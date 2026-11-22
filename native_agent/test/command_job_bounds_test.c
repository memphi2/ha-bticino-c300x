#include "../src/command_job.h"
#include "../src/time_util.h"

#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    struct c300x_command_job job;
    struct pollfd fd;
    unsigned char buffer[8194];
    assert(argc == 5);
    int capture = atoi(argv[2]);
    size_t size = (size_t)atoi(argv[3]);
    size_t emitted = (size_t)atoi(argv[4]);
    assert(size > 0 && size <= 8192);
    memset(buffer, 0xa5, sizeof(buffer));
    c300x_command_job_init(&job);
    assert(!c300x_command_job_start_capture(&job, argv[1], "", NULL, size, 2000));
    assert(!c300x_command_job_start_capture(&job, argv[1], "", (char *)buffer + 1, 0, 2000));
    assert(!c300x_command_job_start(&job, argv[1], "", 0, 0));
    assert(!c300x_command_job_start(&job, "/missing-c300x-test-script", "", 0, 2000));
    assert(c300x_command_job_prepare(&job, &fd) == -1 && fd.fd == -1);
    assert(capture
        ? c300x_command_job_start_capture(&job, argv[1], "", (char *)buffer + 1, size, 2000)
        : c300x_command_job_start(&job, argv[1], "", 0, 2000));
    pid_t pid = job.pid;
    assert(!c300x_command_job_start(&job, argv[1], "", 0, 2000));
    assert(job.pid == pid && job.output_fd >= 0);
    long long deadline = c300x_monotonic_ms() + 3000;
    while (job.pid > 0) {
        assert(c300x_monotonic_ms() < deadline);
        int timeout = c300x_command_job_prepare(&job, &fd);
        assert(timeout >= 0 && timeout <= 50);
        (void)poll(&fd, 1, timeout);
        c300x_command_job_tick(&job);
    }
    assert(job.complete);
    assert(job.failed == (!capture && emitted >= C300X_COMMAND_OUTPUT_SIZE));
    size_t capacity = capture ? size - 1 : C300X_COMMAND_OUTPUT_SIZE - 1;
    assert(job.used == (emitted < capacity ? emitted : capacity));
    assert(strlen(capture ? (char *)buffer + 1 : job.output) == job.used);
    assert(buffer[0] == 0xa5 && buffer[size + 1] == 0xa5);
    assert(c300x_command_job_prepare(&job, &fd) == -1 && fd.fd == -1);
    c300x_command_job_close(&job);
    return 0;
}
