#ifndef C300X_MEDIA_RTSP_IO_H
#define C300X_MEDIA_RTSP_IO_H

#include <stddef.h>
#include <sys/types.h>

#define RTSP_CONNECTION_LIMIT 8

/* One writer per accepted connection. Slots borrow the handler's reference;
 * relay targets retain it under the same lock that protects slot ownership. */
struct c300x_rtsp_writer;
struct c300x_rtsp_writer *c300x_rtsp_writer_create(void);
void c300x_rtsp_writer_retain(struct c300x_rtsp_writer *writer);
void c300x_rtsp_writer_release(struct c300x_rtsp_writer *writer);
/* Aggregate TEARDOWN is final for this connection. Stop retained media targets
 * before replying; control responses remain serialized with in-flight writes. */
void c300x_rtsp_writer_end_media(struct c300x_rtsp_writer *writer);

/* Absolute monotonic deadline, also bounds interrupted/short writes. */
int c300x_rtsp_wait_writable(int fd, long long deadline_ms);
/* Wait for input and service any pending suffix on the borrowed writer.
 * Output wakeups do not restart the input timeout or absolute deadline_ms.
 * deadline_ms is monotonic; 0 means no absolute input deadline.
 * 1 readable, 0 timeout or deadline reached, -1 error. */
int c300x_rtsp_wait_readable(struct c300x_rtsp_writer *writer, int fd, int timeout_seconds,
                             long long deadline_ms);
/* Seconds a client may stay silent before its connection is closed: the
 * teardown wait once that is set, else the session timeout the SETUP answer
 * advertised once the client plays, else 30. Never past deadline_ms
 * (monotonic, 0 means no deadline); 0 when the deadline has passed. */
int c300x_rtsp_read_timeout(int teardown_seconds, int session_seconds, long long deadline_ms);
ssize_t c300x_rtsp_send_pair(struct c300x_rtsp_writer *writer,
                            int fd, const void *first, size_t first_len,
                            const void *second, size_t second_len);
/* Frame length if sent, 0 if dropped or its unsent suffix is retained, -1 on
 * failure. One partial frame per connection is finished before any subsequent
 * media or RTSP response. Input buffers are never borrowed after return. */
ssize_t c300x_rtsp_send_interleaved(struct c300x_rtsp_writer *writer,
                                   int fd, int channel,
                                   const void *packet, size_t packet_len);

/* Caller serializes registry access. Entries contain fd + 1; zero is unused. */
int c300x_rtsp_connection_add(int fds[RTSP_CONNECTION_LIMIT], int fd);
void c300x_rtsp_connections_shutdown(const int fds[RTSP_CONNECTION_LIMIT]);

int parse_interleaved_channel(const char *transport);

void send_rtsp_response(
    struct c300x_rtsp_writer *writer,
    int fd,
    int status,
    const char *cseq,
    const char *headers,
    const char *body
) __attribute__((noinline));

#endif
