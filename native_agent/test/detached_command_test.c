/* Commands the agent starts: bounded, clean, nothing left to reap. */
#include <assert.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "../src/detached_command.h"

static long long now_ms(void)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return now.tv_sec * 1000LL + now.tv_nsec / 1000000;
}

int main(int argc, char **argv)
{
    char script[600], report[600], line[256], fd_name[16];
    int extra[2];
    assert(argc == 2);
    /* The agent ignores SIGPIPE and holds sockets the command must not get. */
    signal(SIGPIPE, SIG_IGN);
    assert(pipe(extra) == 0);

    assert(c300x_run_detached_command("/bin/true", NULL, 0) == 1);
    assert(c300x_run_detached_command("/bin/false", NULL, 0) == 0);
    /* A command that hangs is given up (300 ms in this build). */
    long long start = now_ms();
    assert(c300x_run_detached_command("/bin/sleep", "5", 0) == 0);
    assert(now_ms() - start < 2000);

    snprintf(script, sizeof(script), "%s/report.sh", argv[1]);
    snprintf(report, sizeof(report), "%s/report.txt", argv[1]);
    FILE *file = fopen(script, "w");
    assert(file != NULL);
    fprintf(file, "#!/bin/sh\nls /proc/$$/fd > %s.tmp\ngrep SigIgn /proc/$$/status >> %s.tmp\nmv %s.tmp %s\n",
            report, report, report, report);
    assert(fclose(file) == 0 && chmod(script, 0700) == 0);
    start = now_ms();
    assert(c300x_run_detached_command(script, NULL, 200) == 1);
    assert(now_ms() - start < 150);
    /* The starter is reaped at once; the delayed command belongs to init. */
    assert(waitpid(-1, NULL, WNOHANG) == -1 && errno == ECHILD);
    for (int i = 0; i < 300 && access(report, F_OK) != 0; i++) {
        usleep(10000);
    }
    file = fopen(report, "r");
    assert(file != NULL);
    snprintf(fd_name, sizeof(fd_name), "%d\n", extra[1]);
    while (fgets(line, sizeof(line), file) != NULL) {
        assert(strcmp(line, fd_name) != 0);
        if (strncmp(line, "SigIgn:", 7) == 0) {
            unsigned long long ignored = strtoull(line + 7, NULL, 16);
            assert((ignored & (1ULL << (SIGPIPE - 1))) == 0);
        }
    }
    fclose(file);
    return 0;
}
