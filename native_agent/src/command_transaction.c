#include "command_transaction.h"

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static int spawn_transaction(const char *program, const char *argument, int pipes[2], pid_t *pid)
{
    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attr;
    char *argv[] = {(char *)program, (char *)argument, NULL};
    if (posix_spawn_file_actions_init(&actions) != 0) {
        return 0;
    }
    if (posix_spawnattr_init(&attr) != 0) {
        posix_spawn_file_actions_destroy(&actions);
        return 0;
    }
    int error = posix_spawn_file_actions_adddup2(&actions, pipes[1], STDOUT_FILENO);
    error |= posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    error |= posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
    /* Retain the capture launcher's descriptor boundary and close high pipe FDs. */
    for (int fd = STDERR_FILENO + 1; fd < 256; fd++) {
        error |= posix_spawn_file_actions_addclose(&actions, fd);
    }
    for (int i = 0; i < 2; i++) {
        if (pipes[i] >= 256) {
            error |= posix_spawn_file_actions_addclose(&actions, pipes[i]);
        }
    }
    {
        /* The agent ignores SIGPIPE, and an ignored signal stays ignored
         * across exec: scripts and their pipelines get the default back. */
        sigset_t defaults;
        sigemptyset(&defaults);
        sigaddset(&defaults, SIGPIPE);
        error |= posix_spawnattr_setsigdefault(&attr, &defaults);
    }
    error |= posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_SETSIGDEF);
    error |= posix_spawnattr_setpgroup(&attr, 0);
    if (error == 0) {
        error = posix_spawn(pid, program, &actions, &attr, argv, environ);
    }
    posix_spawnattr_destroy(&attr);
    posix_spawn_file_actions_destroy(&actions);
    return error == 0;
}

int c300x_command_transaction_capture(const char *program, const char *argument,
    char *out, size_t out_len)
{
    int pipes[2], status = 0, read_ok = 1;
    pid_t pid, reaped;
    size_t used = 0;
    if (out == NULL || out_len == 0) {
        return 0;
    }
    out[0] = '\0';
    if (program == NULL || program[0] == '\0' || pipe(pipes) != 0) {
        return 0;
    }
    if (fcntl(pipes[0], F_SETFD, FD_CLOEXEC) < 0
        || fcntl(pipes[1], F_SETFD, FD_CLOEXEC) < 0
        || !spawn_transaction(program, argument, pipes, &pid)) {
        close(pipes[0]);
        close(pipes[1]);
        return 0;
    }
    close(pipes[1]);
    /* Overflow never aborts a write. Drain the rest, then reap even if stdout
     * closed early. EINTR only records shutdown in the caller's signal handler. */
    for (;;) {
        char chunk[1024];
        ssize_t size = read(pipes[0], chunk, sizeof(chunk));
        if (size < 0 && errno == EINTR) {
            continue;
        }
        if (size <= 0) {
            read_ok = size == 0;
            break;
        }
        size_t capacity = out_len - used - 1;
        size_t copied = (size_t)size < capacity ? (size_t)size : capacity;
        memcpy(out + used, chunk, copied);
        used += copied;
    }
    out[used] = '\0';
    close(pipes[0]);
    do {
        reaped = waitpid(pid, &status, 0);
    } while (reaped < 0 && errno == EINTR);
    return read_ok && reaped == pid && WIFEXITED(status) && WEXITSTATUS(status) == 0;
}
