#ifndef C300X_DISPLAY_ALERTS_H
#define C300X_DISPLAY_ALERTS_H

#include "http_request.h"

#define C300X_DISPLAY_ALERTS_POLL_FDS 1
#define C300X_DISPLAY_ALERTS_MAX_BODY 7680
#define C300X_DISPLAY_ALERTS_DEDUP_SLOTS 64
#define C300X_DISPLAY_ALERTS_DEDUP_MS 300000
#define C300X_DISPLAY_ALERTS_DELIVERY_MS 5000

struct c300x_display_alert_receipt {
    char id[33];
    char digest[65];
    long long deadline_ms;
    int outcome;
};

struct c300x_display_alerts {
    int gui_fd;
    int gui_protected;
    /* The C100X adapter has no cancellable alert tone. */
    int sound_supported;
    struct c300x_display_alert_receipt receipts[C300X_DISPLAY_ALERTS_DEDUP_SLOTS];
};

void c300x_display_alerts_init(struct c300x_display_alerts *alerts);
void c300x_display_alerts_handle_api(struct c300x_display_alerts *alerts, int fd,
    const struct request *request);
/* Auth/loopback guards belong to the HTTP router. Zero transfers fd ownership. */
int c300x_display_alerts_handle_ui(struct c300x_display_alerts *alerts, int fd,
    const struct request *request);
int c300x_display_alerts_prepare(const struct c300x_display_alerts *alerts, struct pollfd *fds);
void c300x_display_alerts_tick(struct c300x_display_alerts *alerts, const struct pollfd *fds);
void c300x_display_alerts_close(struct c300x_display_alerts *alerts);

#endif
