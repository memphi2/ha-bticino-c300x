#ifndef C300X_MEDIA_RTSP_IO_H
#define C300X_MEDIA_RTSP_IO_H

#include <stddef.h>
#include <sys/types.h>

#define RTSP_CONNECTION_LIMIT 8

/* Absolute monotonic deadline, also bounds interrupted/short writes. */
int c300x_rtsp_wait_writable(int fd, long long deadline_ms);
/* Wait for input, never past deadline_ms (monotonic, 0 means no deadline).
 * 1 readable, 0 timeout or deadline reached, -1 error. */
int c300x_rtsp_wait_readable(int fd, int timeout_seconds, long long deadline_ms);
/* Seconds a client may stay silent before its connection is closed: the
 * teardown wait once that is set, else the session timeout the SETUP answer
 * advertised once the client plays, else 30. Never past deadline_ms
 * (monotonic, 0 means no deadline); 0 when the deadline has passed. */
int c300x_rtsp_read_timeout(int teardown_seconds, int session_seconds, long long deadline_ms);
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
