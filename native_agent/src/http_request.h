#ifndef C300X_HTTP_REQUEST_H
#define C300X_HTTP_REQUEST_H

#include <poll.h>
#include <stddef.h>

#define REQUEST_BUFFER_SIZE 8192
#define C300X_HTTP_REQUEST_TIMEOUT_MS 500
#define C300X_HTTP_ACCEPT_BUDGET 8

struct request {
    char method[8];
    char path[256];
    char query[256];
    char headers[REQUEST_BUFFER_SIZE];
    char body[REQUEST_BUFFER_SIZE];
    size_t body_len;
};

int parse_request(char *buffer, struct request *request);
int c300x_http_request_status(char *buffer, size_t used, size_t capacity, int *size_error);
int receive_http_request(int client_fd, char *buffer, size_t buffer_len, int *too_large);

#endif
