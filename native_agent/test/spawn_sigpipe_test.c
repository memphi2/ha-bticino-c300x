/* Scripts the agent starts get SIGPIPE at its default, not ignored. */
#include <assert.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "../src/command_job.h"
#include "../src/command_transaction.h"
#include "../src/time_util.h"

static void assert_default_sigpipe(const char *report)
{
    const char *line = strstr(report, "SigIgn:");
    assert(line != NULL);
    unsigned long long ignored = strtoull(line + 7, NULL, 16);
    assert((ignored & (1ULL << (SIGPIPE - 1))) == 0);
}

int main(int argc, char **argv)
{
    char script[600], out[256] = "";
    struct c300x_command_job job;
    struct pollfd fd;
    assert(argc == 2);
    snprintf(script, sizeof(script), "%s/report.sh", argv[1]);
    FILE *file = fopen(script, "w");
    assert(file != NULL);
    fputs("#!/bin/sh\ngrep SigIgn /proc/$$/status\n", file);
    assert(fclose(file) == 0 && chmod(script, 0700) == 0);
    /* As in the agent: a closed reader must not kill it. */
    signal(SIGPIPE, SIG_IGN);

    assert(c300x_command_transaction_capture(script, "x", out, sizeof(out)));
    assert_default_sigpipe(out);

    c300x_command_job_init(&job);
    assert(c300x_command_job_start_capture(&job, script, "x", out, sizeof(out), 2000));
    long long deadline = c300x_monotonic_ms() + 3000;
    while (job.pid > 0) {
        assert(c300x_monotonic_ms() < deadline);
        int timeout = c300x_command_job_prepare(&job, &fd);
        (void)poll(&fd, 1, timeout);
        c300x_command_job_tick(&job);
    }
    assert(job.complete && !job.failed);
    assert_default_sigpipe(out);
    return 0;
}
