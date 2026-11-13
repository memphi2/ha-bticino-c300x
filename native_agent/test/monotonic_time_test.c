#include <assert.h>
#include <sys/time.h>
#include <time.h>

#include "../src/ringer_control.h"
#include "../src/command_job.h"

static long long wall_ms = 1710000000000LL;
static long long monotonic_ms = 10000;

int controlled_gettimeofday(struct timeval *time, void *timezone)
{
    (void)timezone;
    time->tv_sec = (time_t)(wall_ms / 1000);
    time->tv_usec = (suseconds_t)(wall_ms % 1000) * 1000;
    return 0;
}

int controlled_clock_gettime(clockid_t clock, struct timespec *time)
{
    assert(clock == CLOCK_MONOTONIC);
    time->tv_sec = (time_t)(monotonic_ms / 1000);
    time->tv_nsec = (long)(monotonic_ms % 1000) * 1000000;
    return 0;
}

#define gettimeofday controlled_gettimeofday
#define clock_gettime controlled_clock_gettime
#include "../src/time_util.c"
#undef clock_gettime
#undef gettimeofday

int main(void)
{
    struct c300x_ringer_control ringer = {0};
    struct c300x_command_job command = {0};
    struct pollfd socket;
    ringer.client_fd = 42; /* Only deadline calculation is exercised, no I/O. */
    ringer.deadline_ms = c300x_monotonic_ms() + 4000;
    command.pid = 1;
    command.deadline_ms = ringer.deadline_ms;

    wall_ms += 12 * 60 * 60 * 1000LL;
    monotonic_ms += 1250;
    assert(c300x_ringer_control_timeout_ms(&ringer) == 2750);
    assert(c300x_command_job_prepare(&command, &socket) == 50);
    wall_ms -= 48 * 60 * 60 * 1000LL;
    monotonic_ms += 1250;
    assert(c300x_ringer_control_timeout_ms(&ringer) == 1500);
    monotonic_ms += 1475;
    assert(c300x_command_job_prepare(&command, &socket) == 25);
    monotonic_ms += 25;
    assert(c300x_ringer_control_timeout_ms(&ringer) == 0);
    assert(c300x_command_job_prepare(&command, &socket) == 0);
    return 0;
}
