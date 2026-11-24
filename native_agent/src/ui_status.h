#ifndef C300X_UI_STATUS_H
#define C300X_UI_STATUS_H

#include <stddef.h>

/*
 * What the station's own settings page may show about Home Assistant while it
 * cannot be reached. Of the callback URL only scheme, host and port leave the
 * agent: the path carries the webhook id.
 */
int c300x_ui_status_origin(const char *url, char *out, size_t out_len);

int c300x_ui_status_json(
    const char *version,
    const char *firmware,
    const char *webhook_url,
    int connected,
    long last_seen_at,
    long now,
    char *out,
    size_t out_len
);

#endif
