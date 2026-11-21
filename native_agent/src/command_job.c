#include "command_job.h"
#include "time_util.h"

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

/* A started script, and whatever it starts in turn (the patch script
 * restarts the GUI), must not keep the agent's sockets open: a listening
 * media socket held by the GUI blocks the port for the next agent start. */
#define C300X_COMMAND_INHERITED_FD_LIMIT 256

void c300x_command_job_init(struct c300x_command_job *job)
{
    memset(job, 0, sizeof(*job));
    job->output_fd = -1;
}

static int start_job(struct c300x_command_job *job, const char *program,
    char *const argv[], int dynamic_homepage, int timeout_ms, int wait_only)
{
    int pipes[2];
    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attr;
    size_t count = 0, used = 0;
    char **env;
    int error;

    if (job->pid > 0 || (!wait_only && timeout_ms <= 0) || pipe(pipes) != 0) {
        return 0;
    }
    if (fcntl(pipes[0], F_SETFD, FD_CLOEXEC) < 0
        || fcntl(pipes[1], F_SETFD, FD_CLOEXEC) < 0
        || fcntl(pipes[0], F_SETFL, O_NONBLOCK) < 0) {
        goto fail_pipe;
    }
    while (environ[count] != NULL) {
        count++;
    }
    env = calloc(count + 2, sizeof(*env));
    if (env == NULL) {
        goto fail_pipe;
    }
    for (size_t i = 0; i < count; i++) {
        if (!dynamic_homepage || strncmp(environ[i], "C300X_QML_DYNAMIC_HOME_PAGE=",
                sizeof("C300X_QML_DYNAMIC_HOME_PAGE=") - 1) != 0) {
            env[used++] = environ[i];
        }
    }
    if (dynamic_homepage) {
        env[used++] = "C300X_QML_DYNAMIC_HOME_PAGE=1";
    }
    if (posix_spawn_file_actions_init(&actions) != 0) {
        goto fail_env;
    }
    if (posix_spawnattr_init(&attr) != 0) {
        goto fail_actions;
    }
    error = wait_only
        ? posix_spawn_file_actions_addopen(&actions, STDOUT_FILENO, "/dev/null", O_WRONLY, 0)
        : posix_spawn_file_actions_adddup2(&actions, pipes[1], STDOUT_FILENO);
    error |= posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    error |= posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
    /* Closing a descriptor that is not open is not an error for spawn. */
    /* Preserve the old service launcher close range, including higher FDs. */
    long fd_limit = wait_only ? sysconf(_SC_OPEN_MAX) : C300X_COMMAND_INHERITED_FD_LIMIT;
    if (fd_limit < 0) {
        fd_limit = 1024;
    }
    if (fd_limit > 4096) {
        fd_limit = 4096;
    }
    for (int fd = STDERR_FILENO + 1; fd < fd_limit; fd++) {
        error |= posix_spawn_file_actions_addclose(&actions, fd);
    }
    error |= posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETPGROUP);
    error |= posix_spawnattr_setpgroup(&attr, 0);
    if (error == 0) {
        c300x_command_job_init(job);
        error = posix_spawn(&job->pid, program, &actions, &attr, argv, env);
    }
    posix_spawnattr_destroy(&attr);
    posix_spawn_file_actions_destroy(&actions);
    free(env);
    if (error != 0) {
        job->pid = 0;
        goto fail_pipe;
    }
    close(pipes[1]);
    job->output_fd = pipes[0];
    job->deadline_ms = timeout_ms > 0 ? c300x_monotonic_ms() + timeout_ms : 0;
    return 1;

fail_actions:
    posix_spawn_file_actions_destroy(&actions);
fail_env:
    free(env);
fail_pipe:
    close(pipes[0]);
    close(pipes[1]);
    return 0;
}

int c300x_command_job_start(struct c300x_command_job *job, const char *program,
    const char *argument, int dynamic_homepage, int timeout_ms)
{
    char *argv[] = {(char *)program, (char *)argument, NULL};
    return start_job(job, program, argv, dynamic_homepage, timeout_ms, 0);
}

int c300x_command_job_start_wait(struct c300x_command_job *job, const char *program,
    char *const argv[], int timeout_ms)
{
    return start_job(job, program, argv, 0, timeout_ms, 1);
}

int c300x_command_job_start_capture(struct c300x_command_job *job, const char *program,
    const char *argument, char *out, size_t out_len, int timeout_ms)
{
    if (out == NULL || out_len == 0
        || !c300x_command_job_start(job, program, argument, 0, timeout_ms)) {
        return 0;
    }
    out[0] = '\0';
    job->capture_output = out;
    job->capture_size = out_len;
    return 1;
}

int c300x_command_job_prepare(const struct c300x_command_job *job, struct pollfd *fd)
{
    long long remaining;
    *fd = (struct pollfd){.fd = job->output_fd, .events = POLLIN};
    if (job->pid <= 0) {
        return -1;
    }
    if (job->deadline_ms == 0) {
        return 50;
    }
    /* Reap only while a job exists, including after stdout has closed. */
    remaining = job->deadline_ms - c300x_monotonic_ms();
    return job->complete ? 50 : remaining <= 0 ? 0 : remaining < 50 ? (int)remaining : 50;
}

static void close_output(struct c300x_command_job *job)
{
    if (job->output_fd >= 0) {
        close(job->output_fd);
        job->output_fd = -1;
    }
}

void c300x_command_job_tick(struct c300x_command_job *job)
{
    int status = 0;
    int wait_error;
    pid_t reaped;
    if (job->pid <= 0) {
        return;
    }
    reaped = waitpid(job->pid, &status, WNOHANG);
    wait_error = errno;
    /* A noisy child cannot monopolize a main-loop iteration. */
    for (int reads = 0; job->output_fd >= 0 && reads < 8; reads++) {
        char chunk[1024];
        ssize_t size = read(job->output_fd, chunk, sizeof(chunk));
        if (size > 0) {
            char *output = job->capture_output != NULL ? job->capture_output : job->output;
            size_t size_limit = job->capture_output != NULL ? job->capture_size : sizeof(job->output);
            size_t capacity = size_limit - job->used - 1;
            size_t copied = (size_t)size < capacity ? (size_t)size : capacity;
            memcpy(output + job->used, chunk, copied);
            job->used += copied;
            output[job->used] = '\0';
            if (copied != (size_t)size && job->capture_output == NULL) {
                job->failed = 1;
            }
        } else if (size == 0 || (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) {
            close_output(job);
        } else {
            break;
        }
    }
    if (!job->complete && (job->failed
        || (job->deadline_ms > 0 && c300x_monotonic_ms() >= job->deadline_ms))) {
        job->failed = 1;
        job->complete = 1;
        if (reaped == 0 || (reaped < 0 && wait_error != ECHILD)) {
            (void)kill(-job->pid, SIGKILL);
        }
        close_output(job);
    }
    if (reaped == job->pid || (reaped < 0 && wait_error == ECHILD)) {
        job->failed |= reaped < 0 || !WIFEXITED(status) || WEXITSTATUS(status) != 0;
        job->exit_status = reaped > 0 && WIFEXITED(status) ? WEXITSTATUS(status) : -1;
        job->pid = 0;
        job->complete = 1;
        close_output(job);
    }
}

void c300x_command_job_close(struct c300x_command_job *job)
{
    if (job->pid > 0) {
        (void)kill(-job->pid, SIGKILL);
        (void)waitpid(job->pid, NULL, WNOHANG);
    }
    close_output(job);
}
