#ifndef C300X_DISPLAY_TOUCH_H
#define C300X_DISPLAY_TOUCH_H

#include <stddef.h>

#include "c300x_agent.h"

#define C300X_DISPLAY_TOUCH_STATE_LEN 32
#define C300X_DISPLAY_TOUCH_HASH_LEN 65

/* The swipe threshold of the Qt 4 display: 4 px as shipped, so a tap with a
 * slightly moving finger becomes a swipe and is lost. The patch makes it 16 px.
 * It belongs to the Display patch and is applied and restored with it. */
struct c300x_display_touch_status {
    int patched;
    int backup_present;
    int changed;
    /* The running display keeps the replaced file open, so the root file
     * system cannot go read-only again before the display is restarted. */
    int root_writable;
    char state[C300X_DISPLAY_TOUCH_STATE_LEN];
    char file_sha256[C300X_DISPLAY_TOUCH_HASH_LEN];
    char error[C300X_MAX_ERROR_LEN];
};

int c300x_display_touch_read_status(struct c300x_display_touch_status *status);
int c300x_display_touch_apply(
    struct c300x_display_touch_status *status,
    char *error,
    size_t error_len
);
int c300x_display_touch_restore(
    struct c300x_display_touch_status *status,
    char *error,
    size_t error_len
);
/* Command-line entry: prints one JSON line; the Display patch script calls it. */
int c300x_display_touch_cli(const char *action);

#endif
