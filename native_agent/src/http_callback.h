#ifndef C300X_HTTP_CALLBACK_H
#define C300X_HTTP_CALLBACK_H

#define C300X_EVENT_TOKEN_HEADER "X-Bticino-C300X-Event-Token"

int c300x_http_post_callback(const char *url, const char *token, const char *event_json, int timeout_ms);

#endif
