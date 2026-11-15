#ifndef C300X_TOUCH_TONE_H
#define C300X_TOUCH_TONE_H

#include <poll.h>
#include <stddef.h>
#include "http_request.h"

#define C300X_TOUCH_TONE_POLL_FDS 2
struct c300x_touch_tone {
    int gui_fd, client_fd, enabled, requested;
    long long deadline_ms;
    char id[33];
    char session[33];
    int revision;
    void (*changed)(void *ctx);
    void *ctx;
};

void c300x_touch_tone_init(struct c300x_touch_tone *tone, void (*changed)(void *), void *ctx);
void c300x_touch_tone_status(const struct c300x_touch_tone *tone, char *body, size_t size);
void c300x_touch_tone_request(struct c300x_touch_tone *tone, int fd, int enabled);
int c300x_touch_tone_next(struct c300x_touch_tone *tone, int fd, const char *query);
int c300x_touch_tone_report(struct c300x_touch_tone *tone, const char *session, int revision, int enabled);
int c300x_touch_tone_prepare(const struct c300x_touch_tone *tone, struct pollfd *fds);
void c300x_touch_tone_tick(struct c300x_touch_tone *tone, const struct pollfd *fds);
void c300x_touch_tone_close(struct c300x_touch_tone *tone);
void c300x_touch_tone_handle_api(struct c300x_touch_tone *tone, int fd, const struct request *request);
int c300x_touch_tone_handle_ui(struct c300x_touch_tone *tone, int fd, const struct request *request);

#endif
