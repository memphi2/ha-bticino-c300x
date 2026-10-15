#ifndef C300X_HTTPS_CLIENT_H
#define C300X_HTTPS_CLIENT_H

#include <stddef.h>

int c300x_https_available(void);

/* Errors are fixed identifiers; URLs, tokens and server bodies are never logged. */
int c300x_https_post(
    const char *url, const char *token_header, const char *token, const char *body,
    char *response, size_t response_len, int timeout_ms,
    long *http_status, const char **error
);

#endif
