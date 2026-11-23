#include "media_rtsp_reader.h"
#include "media_rtsp_io.h"
#include "media_sip.h"

#include <string.h>
#include <sys/socket.h>

static void drain_rtsp_interleaved_payload(
    struct c300x_rtsp_writer *writer,
    int fd,
    size_t len,
    int timeout_seconds,
    long long deadline_ms
) {
    unsigned char scratch[256];
    size_t remaining = len;

    while (remaining > 0) {
        size_t chunk = remaining < sizeof(scratch) ? remaining : sizeof(scratch);
        if (c300x_rtsp_wait_readable(writer, fd, timeout_seconds, deadline_ms) <= 0) {
            return;
        }
        ssize_t n = recv(fd, scratch, chunk, 0);
        if (n <= 0) {
            return;
        }
        remaining -= (size_t)n;
    }
}

static void rtsp_buf_compact(rtsp_read_buffer_t *buf) {
    if (buf->start == 0) {
        return;
    }
    if (buf->len > 0) {
        memmove(buf->data, buf->data + buf->start, buf->len);
    }
    buf->start = 0;
}

static int rtsp_buf_fill(rtsp_read_buffer_t *buf, int fd, int timeout_seconds) {
    rtsp_buf_compact(buf);
    if (buf->len + 1 >= buf->cap) {
        return -1;
    }
    int ready = c300x_rtsp_wait_readable(buf->writer, fd, timeout_seconds, buf->deadline_ms);
    if (ready <= 0) {
        return ready;
    }
    ssize_t n = recv(fd, buf->data + buf->len, buf->cap - 1 - buf->len, 0);
    if (n <= 0) {
        return -1;
    }
    buf->len += (size_t)n;
    return 1;
}

// Ensure at least `want` bytes are buffered. 1 ok, 0 timeout, -1 error.
static int rtsp_buf_ensure(
    rtsp_read_buffer_t *buf,
    int fd,
    size_t want,
    int timeout_seconds
) {
    while (buf->len < want) {
        int r = rtsp_buf_fill(buf, fd, timeout_seconds);
        if (r <= 0) {
            return r;
        }
    }
    return 1;
}

static void rtsp_buf_consume(rtsp_read_buffer_t *buf, size_t n) {
    if (n >= buf->len) {
        buf->start = 0;
        buf->len = 0;
        return;
    }
    buf->start += n;
    buf->len -= n;
}

static void rtsp_buf_discard(
    rtsp_read_buffer_t *buf,
    int fd,
    size_t n,
    int timeout_seconds
) {
    size_t from_buf = buf->len < n ? buf->len : n;
    rtsp_buf_consume(buf, from_buf);
    n -= from_buf;
    if (n > 0) {
        drain_rtsp_interleaved_payload(buf->writer, fd, n, timeout_seconds, buf->deadline_ms);
    }
}

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
) {
    if (
        buf == NULL
        || request == NULL
        || request_size < 2
        || interleaved == NULL
        || interleaved_channel == NULL
        || interleaved_len == NULL
    ) {
        return RTSP_READ_ERROR;
    }
    request[0] = '\0';
    *interleaved_channel = -1;
    *interleaved_len = 0;

    int r = rtsp_buf_ensure(buf, fd, 1, timeout_seconds);
    if (r == 0) {
        return RTSP_READ_TIMEOUT;
    }
    if (r < 0) {
        return RTSP_READ_ERROR;
    }

    if (buf->data[buf->start] == '$') {
        if (rtsp_buf_ensure(buf, fd, 4, timeout_seconds) <= 0) {
            return RTSP_READ_ERROR;
        }
        const unsigned char *hdr = buf->data + buf->start;
        size_t frame_len = ((size_t)hdr[2] << 8) | hdr[3];
        *interleaved_channel = hdr[1];
        if (frame_len > interleaved_size) {
            rtsp_buf_consume(buf, 4);
            rtsp_buf_discard(buf, fd, frame_len, timeout_seconds);
            return RTSP_READ_INTERLEAVED;
        }
        if (rtsp_buf_ensure(buf, fd, 4 + frame_len, timeout_seconds) <= 0) {
            return RTSP_READ_ERROR;
        }
        memcpy(interleaved, buf->data + buf->start + 4, frame_len);
        rtsp_buf_consume(buf, 4 + frame_len);
        *interleaved_len = frame_len;
        return RTSP_READ_INTERLEAVED;
    }

    const size_t max_request = request_size - 1;
    for (;;) {
        buf->data[buf->start + buf->len] = '\0';
        char *text = (char *)(buf->data + buf->start);
        char *header_end = strstr(text, "\r\n\r\n");
        if (header_end != NULL) {
            size_t header_len = (size_t)(header_end + 4 - text);
            int body_len = c300x_media_sip_content_length(text);
            size_t message_len =
                header_len + (body_len > 0 ? (size_t)body_len : 0);
            if (message_len > max_request) {
                return RTSP_READ_ERROR;
            }
            if (buf->len >= message_len) {
                memcpy(request, text, message_len);
                request[message_len] = '\0';
                rtsp_buf_consume(buf, message_len);
                return RTSP_READ_REQUEST;
            }
        }
        if (buf->len >= max_request) {
            return RTSP_READ_ERROR;
        }
        if (rtsp_buf_fill(buf, fd, timeout_seconds) <= 0) {
            return RTSP_READ_ERROR;
        }
    }
}
