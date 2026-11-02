#include "command_job.h"
#include "time_util.h"
#include "http_util.h"

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

void c300x_command_job_init(struct c300x_command_job *job)
{
    memset(job, 0, sizeof(*job));
    job->output_fd = -1;
}

int c300x_command_job_start(struct c300x_command_job *job, const char *program,
    const char *argument, int dynamic_homepage, int timeout_ms)
{
    int pipes[2];
    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attr;
    size_t count = 0, used = 0;
    char **env;
    char *argv[] = {(char *)program, (char *)argument, NULL};
    int error;

    if (job->pid > 0 || timeout_ms <= 0 || pipe(pipes) != 0) {
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
    error = posix_spawn_file_actions_adddup2(&actions, pipes[1], STDOUT_FILENO);
    error |= posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    error |= posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
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
    job->deadline_ms = c300x_monotonic_ms() + timeout_ms;
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

int c300x_command_job_prepare(const struct c300x_command_job *job, struct pollfd *fd)
{
    long long remaining;
    *fd = (struct pollfd){.fd = job->output_fd, .events = POLLIN};
    if (job->pid <= 0) {
        return -1;
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
            size_t capacity = sizeof(job->output) - job->used - 1;
            size_t copied = (size_t)size < capacity ? (size_t)size : capacity;
            memcpy(job->output + job->used, chunk, copied);
            job->used += copied;
            job->output[job->used] = '\0';
            if (copied != (size_t)size) {
                job->failed = 1;
            }
        } else if (size == 0 || (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) {
            close_output(job);
        } else {
            break;
        }
    }
    if (!job->complete && (job->failed || c300x_monotonic_ms() >= job->deadline_ms)) {
        job->failed = 1;
        job->complete = 1;
        if (reaped == 0 || (reaped < 0 && wait_error != ECHILD)) {
            (void)kill(-job->pid, SIGKILL);
        }
        close_output(job);
    }
    if (reaped == job->pid || (reaped < 0 && wait_error == ECHILD)) {
        job->failed |= reaped < 0 || !WIFEXITED(status) || WEXITSTATUS(status) != 0;
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

int c300x_command_capture(
    const char *program,
    const char *argument,
    char *out,
    size_t out_len,
    int timeout_ms,
    int *exit_code
)
{
    const int interval_ms = 50;
    int pipe_fd[2];
    int status = 0;
    int waited_ms = 0;
    int child_done = 0;
    size_t used = 0;
    pid_t pid;

    if (out_len > 0) {
        out[0] = '\0';
    }
    if (exit_code != NULL) {
        *exit_code = -1;
    }
    if (program == NULL || program[0] == '\0' || access(program, X_OK) != 0) {
        return 0;
    }
    if (pipe(pipe_fd) != 0) {
        return 0;
    }
    pid = fork();
    if (pid < 0) {
        close(pipe_fd[0]);
        close(pipe_fd[1]);
        return 0;
    }
    if (pid == 0) {
        int null_fd;
        close(pipe_fd[0]);
        (void)dup2(pipe_fd[1], STDOUT_FILENO);
        null_fd = open("/dev/null", O_WRONLY);
        if (null_fd >= 0) {
            (void)dup2(null_fd, STDERR_FILENO);
            close(null_fd);
        }
        close(pipe_fd[1]);
        execl(program, program, argument, (char *)NULL);
        _exit(127);
    }
    close(pipe_fd[1]);
    set_fd_nonblocking(pipe_fd[0]);

    while (!child_done) {
        for (;;) {
            char discard[256];
            size_t capacity = out_len > used + 1 ? out_len - used - 1 : 0;
            ssize_t read_size = read(
                pipe_fd[0],
                capacity > 0 ? out + used : discard,
                capacity > 0 ? capacity : sizeof(discard)
            );
            if (read_size > 0) {
                if (capacity > 0) {
                    used += (size_t)read_size;
                }
                continue;
            }
            if (read_size < 0 && errno == EINTR) {
                continue;
            }
            break;
        }
        if (waitpid(pid, &status, WNOHANG) == pid) {
            child_done = 1;
            break;
        }
        if (waited_ms >= timeout_ms) {
            (void)kill(pid, SIGKILL);
            (void)waitpid(pid, &status, 0);
            close(pipe_fd[0]);
            if (out_len > 0) {
                out[used < out_len ? used : out_len - 1] = '\0';
            }
            return 0;
        }
        (void)poll(NULL, 0, interval_ms);
        waited_ms += interval_ms;
    }
    for (;;) {
        char discard[256];
        size_t capacity = out_len > used + 1 ? out_len - used - 1 : 0;
        ssize_t read_size = read(
            pipe_fd[0],
            capacity > 0 ? out + used : discard,
            capacity > 0 ? capacity : sizeof(discard)
        );
        if (read_size > 0) {
            if (capacity > 0) {
                used += (size_t)read_size;
            }
            continue;
        }
        if (read_size < 0 && errno == EINTR) {
            continue;
        }
        break;
    }
    close(pipe_fd[0]);
    if (out_len > 0) {
        out[used < out_len ? used : out_len - 1] = '\0';
    }
    if (exit_code != NULL && WIFEXITED(status)) {
        *exit_code = WEXITSTATUS(status);
    }
    return WIFEXITED(status) && WEXITSTATUS(status) == 0;
}

