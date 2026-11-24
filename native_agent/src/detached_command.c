#include "detached_command.h"

#include <errno.h>
#include <signal.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#ifndef C300X_DETACHED_COMMAND_WAIT_MS
#define C300X_DETACHED_COMMAND_WAIT_MS 20000
#endif

static void pause_ms(long ms)
{
    struct timespec left = {ms / 1000, (ms % 1000) * 1000000L};
    while (nanosleep(&left, &left) != 0 && errno == EINTR) {
    }
}

static void close_extra_fds(void)
{
    long max_fd = sysconf(_SC_OPEN_MAX);
    if (max_fd < 0 || max_fd > 4096) {
        max_fd = max_fd < 0 ? 1024 : 4096;
    }
    for (long fd = STDERR_FILENO + 1; fd < max_fd; fd++) {
        close((int)fd);
    }
}

int c300x_run_detached_command(const char *program, const char *argument, int delay_ms)
{
    int status = 0;
    pid_t pid = fork();
    if (pid < 0) {
        return 0;
    }
    if (pid == 0) {
        /* Before the delay: no listener or client socket stays open in a
         * child that outlives a restarting agent. */
        close_extra_fds();
        signal(SIGPIPE, SIG_DFL);
        if (delay_ms > 0) {
            pid_t runner = fork();
            if (runner != 0) {
                _exit(runner < 0);
            }
            (void)setsid();
            pause_ms(delay_ms);
        }
        if (argument != NULL) {
            execl(program, program, argument, (char *)NULL);
        } else {
            execl(program, program, (char *)NULL);
        }
        _exit(127);
    }
    for (long waited = 0;; waited += 10) {
        pid_t done = waitpid(pid, &status, WNOHANG);
        if (done == pid) {
            return WIFEXITED(status) && WEXITSTATUS(status) == 0;
        }
        if ((done < 0 && errno != EINTR) || waited >= C300X_DETACHED_COMMAND_WAIT_MS) {
            /* Hung: never hold the agent loop for it. */
            (void)kill(pid, SIGKILL);
            (void)waitpid(pid, &status, 0);
            return 0;
        }
        pause_ms(10);
    }
}
