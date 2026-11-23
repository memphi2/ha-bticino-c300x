#ifndef C300X_DISPLAY_REGISTRATION_H
#define C300X_DISPLAY_REGISTRATION_H

#include "c300x_agent.h"

#define C300X_MAX_URL_LEN 512

struct c300x_callback_queue;
int c300x_display_callback_submit(struct c300x_callback_queue *queue, const char *url,
    const char *secret, int timeout_ms, const char *body, size_t response_len);
void c300x_display_boot_notice(struct c300x_callback_queue *queue, const char *url,
    const char *secret, int timeout_ms, const char *instance_id);

int c300x_display_registration_load(const struct c300x_config *config,
    char url[C300X_MAX_URL_LEN], char secret[C300X_MAX_TOKEN_LEN]);
int c300x_display_registration_save(const struct c300x_config *config,
    const char *url, const char *secret);
int c300x_display_registration_clear(const struct c300x_config *config);

#endif
