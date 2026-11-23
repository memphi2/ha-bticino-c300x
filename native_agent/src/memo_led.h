#ifndef C300X_MEMO_LED_H
#define C300X_MEMO_LED_H

struct c300x_memo_led {
    const char *text_root;
    const char *voice_root;
    int claimed;
    int release_pending;
    int claim_dir;
    struct memo_scan *scan;
    int scan_fd, watch_fd, obsolete;
};

void c300x_memo_led_init(struct c300x_memo_led *led, const char *text, const char *voice);
void c300x_memo_led_close(struct c300x_memo_led *led);
int c300x_memo_led_present(void);
int c300x_memo_led_watch(void);
void c300x_memo_led_update(struct c300x_memo_led *led, int unread);
int c300x_memo_led_pollfd(const struct c300x_memo_led *led);
void c300x_memo_led_ready(struct c300x_memo_led *led);
int c300x_memo_led_event(struct c300x_memo_led *led, const char *topic, const char *body);

#endif
