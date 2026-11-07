#ifndef C300X_DISPLAY_CALLBACK_H
#define C300X_DISPLAY_CALLBACK_H

#include <stddef.h>

int c300x_display_post(
    const char *webhook_url,
    const char *shared_secret,
    int timeout_ms,
    const char *body,
    char *response,
    size_t response_len
);

#endif
