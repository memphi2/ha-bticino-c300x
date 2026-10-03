#ifndef C300X_MEDIA_TEARDOWN_PATCH_H
#define C300X_MEDIA_TEARDOWN_PATCH_H

#include <stddef.h>

#define C300X_MEDIA_TEARDOWN_STATE_LEN 16
#define C300X_MEDIA_TEARDOWN_ERROR_LEN 96

struct c300x_media_teardown_status {
    int supported;
    int patched;
    int backup_present;
    char state[C300X_MEDIA_TEARDOWN_STATE_LEN];
    char error[C300X_MEDIA_TEARDOWN_ERROR_LEN];
};

int c300x_media_teardown_read_status(struct c300x_media_teardown_status *status);

int c300x_media_teardown_apply(
    struct c300x_media_teardown_status *status,
    char *error,
    size_t error_len
);

int c300x_media_teardown_restore(
    struct c300x_media_teardown_status *status,
    char *error,
    size_t error_len
);

#endif
