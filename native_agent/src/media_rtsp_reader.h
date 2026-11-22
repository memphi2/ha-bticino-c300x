#ifndef C300X_MEDIA_RTSP_READER_H
#define C300X_MEDIA_RTSP_READER_H

#include <stddef.h>

typedef enum {
    RTSP_READ_ERROR = -1,
    RTSP_READ_TIMEOUT = 0,
    RTSP_READ_REQUEST = 1,
    RTSP_READ_INTERLEAVED = 2,
} rtsp_read_result_t;

typedef struct {
    unsigned char *data;
    size_t cap;
    size_t start;
    size_t len;
    /* Monotonic time after which no read waits any longer; 0 means none. */
    long long deadline_ms;
} rtsp_read_buffer_t;

/* Private media framing boundary, not a session or socket owner.
 * One reader per connection; caller owns the backing buffer (cap >= 2), fd,
 * and timeout policy. No allocation, locks, threads, or background work.
 * A complete request includes its body. Oversized interleaved payloads are
 * discarded and return INTERLEAVED with length zero. ERROR is terminal;
 * TIMEOUT is returned only before the first byte of a new frame.
 * The caller closes the connection on either ERROR or TIMEOUT. */
rtsp_read_result_t c300x_media_rtsp_read(
    rtsp_read_buffer_t *buf,
    int fd,
    char *request,
    size_t request_size,
    unsigned char *interleaved,
    size_t interleaved_size,
    int *interleaved_channel,
    size_t *interleaved_len,
    int timeout_seconds
);

#endif
