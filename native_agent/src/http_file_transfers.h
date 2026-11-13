#ifndef C300X_HTTP_FILE_TRANSFERS_H
#define C300X_HTTP_FILE_TRANSFERS_H

#include <poll.h>
#include <stddef.h>
#include <stdio.h>

#define C300X_HTTP_MAX_FILE_TRANSFERS 4
#define C300X_HTTP_FILE_BUFFER_SIZE 8192
#define C300X_HTTP_FILE_IDLE_TIMEOUT_MS 2000

struct c300x_http_file_transfer {
    int fd;
    FILE *file;
    char *buffer;
    size_t used;
    size_t sent;
    long remaining;
    long long deadline;
};

struct c300x_http_file_transfers {
    struct c300x_http_file_transfer slots[C300X_HTTP_MAX_FILE_TRANSFERS];
};

void c300x_http_file_transfers_init(struct c300x_http_file_transfers *transfers);
/* On success the slot owns fd; otherwise the caller still owns it. */
int c300x_http_file_transfers_start(struct c300x_http_file_transfers *transfers,
    int fd, const char *path, const char *content_type);
int c300x_http_file_transfers_owns(const struct c300x_http_file_transfers *transfers, int fd);
int c300x_http_file_transfers_prepare(struct c300x_http_file_transfers *transfers,
    struct pollfd *fds, long long now);
void c300x_http_file_transfers_handle(struct c300x_http_file_transfers *transfers,
    const struct pollfd *fds, long long now);
void c300x_http_file_transfers_close(struct c300x_http_file_transfers *transfers);

#endif
