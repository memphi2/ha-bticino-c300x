#ifndef C300X_DEVICE_USER_LABEL_H
#define C300X_DEVICE_USER_LABEL_H

#include "device_detect.h"

#include <stddef.h>

struct c300x_command_job;

/* Trim ASCII white space in place; returns the first kept character. */
const char *c300x_label_trim(char *value);

/* The label is written by the Display patch script: it must be installed, and
 * the station one with a Display patch. A C100X has none; its user and routing
 * are set up, only the label is not shown. */
int c300x_label_script_usable(const char *script);

/* Whether a Qt 5 status confirms the label on a running, active overlay. */
int c300x_label_qt5_state_ok(const char *body, int applying);

/* Whether a label apply/restore by the patch script succeeded. */
int c300x_label_result_ok(char *output, int applying);

/* Start the label apply/restore of the patch script as a QML write job: the
 * write deadline, then SIGTERM and the grace period for the script's rollback.
 * The caller owns `out` until the job completes or is closed. */
int c300x_label_job_start(struct c300x_command_job *job, const char *script,
    int restoring, char *out, size_t out_len);

/* Answer a label write that passed its deadline. The script exits 130 only
 * once its rollback is complete. */
void c300x_label_send_timeout(int fd, int exit_status);

#endif
