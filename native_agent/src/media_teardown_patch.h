#ifndef C300X_MEDIA_TEARDOWN_PATCH_H
#define C300X_MEDIA_TEARDOWN_PATCH_H

#include <stddef.h>

#define C300X_MEDIA_TEARDOWN_STATE_LEN 16
#define C300X_MEDIA_TEARDOWN_ERROR_LEN 96
#define C300X_MEDIA_TEARDOWN_SIZE 186932u
#define C300X_MEDIA_TEARDOWN_STOCK_SHA256 \
    "97b61ad80e67c1b3ea494956568645b93c7fe3ef359f77af9c7e2ad6dff1bf9e"
#define C300X_MEDIA_TEARDOWN_PATCHED_SHA256 \
    "45f776fee4bb4b5fd020f19e961c48754fe3513ea6c70266a817a03639fb014a"

struct c300x_media_teardown_status {
    int supported;
    int patched;
    int backup_present;
    int changed;
    char state[C300X_MEDIA_TEARDOWN_STATE_LEN];
    char error[C300X_MEDIA_TEARDOWN_ERROR_LEN];
};

int c300x_media_teardown_read_status(struct c300x_media_teardown_status *status);
int c300x_media_teardown_target_name(char *buffer, size_t buffer_len);
int c300x_media_teardown_is_active(void);

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
