#ifndef C300X_COMMAND_JOB_H
#define C300X_COMMAND_JOB_H

#include <poll.h>
#include <stddef.h>
#include <sys/types.h>

#define C300X_COMMAND_OUTPUT_SIZE 4096

struct c300x_command_job {
    pid_t pid;
    int output_fd;
    int failed;
    int complete;
    long long deadline_ms;
    size_t used;
    char output[C300X_COMMAND_OUTPUT_SIZE];
    char *capture_output;
    size_t capture_size;
};

void c300x_command_job_init(struct c300x_command_job *job);
int c300x_command_job_start(struct c300x_command_job *job, const char *program,
    const char *argument, int dynamic_homepage, int timeout_ms);
/* Legacy capture semantics: retain a bounded prefix and discard excess output.
 * The caller owns the buffer until completion/close; ordinary jobs still fail
 * on overflow of their unchanged 4096-byte buffer. */
int c300x_command_job_start_capture(struct c300x_command_job *job, const char *program,
    const char *argument, char *out, size_t out_len, int timeout_ms);
int c300x_command_job_prepare(const struct c300x_command_job *job, struct pollfd *fd);
void c300x_command_job_tick(struct c300x_command_job *job);
void c300x_command_job_close(struct c300x_command_job *job);

#endif
