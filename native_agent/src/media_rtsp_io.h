#ifndef C300X_MEDIA_RTSP_IO_H
#define C300X_MEDIA_RTSP_IO_H

#include <stddef.h>
#include <sys/types.h>

#define RTSP_CONNECTION_LIMIT 8

/* Absolute monotonic deadline, also bounds interrupted/short writes. */
int c300x_rtsp_wait_writable(int fd, long long deadline_ms);
ssize_t c300x_rtsp_send_pair(int fd, const void *first, size_t first_len,
                            const void *second, size_t second_len);

/* Caller serializes registry access. Entries contain fd + 1; zero is unused. */
int c300x_rtsp_connection_add(int fds[RTSP_CONNECTION_LIMIT], int fd);
void c300x_rtsp_connections_shutdown(const int fds[RTSP_CONNECTION_LIMIT]);

int parse_client_port(const char *transport);
int parse_interleaved_channel(const char *transport);

void send_rtsp_response(
    int fd,
    int status,
    const char *cseq,
    const char *headers,
    const char *body
) __attribute__((noinline));

#endif
