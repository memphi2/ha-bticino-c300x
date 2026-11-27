#include "media_rtsp_io.h"
#include "media_rtsp_clients.h"
#include "time_util.h"

#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <time.h>

/* Media forwarding visits clients sequentially: locking and all writes share
 * one short budget. Drop an unstarted frame; retain at most one started tail.
 * A connection that takes no whole frame for the stall limit is closed. */
#define RTSP_FRAME_WRITE_MS 250
#define RTSP_RESPONSE_MS 2000
#define RTSP_STALL_LIMIT_MS 5000

enum rtsp_message { RTSP_RESPONSE = 0, RTSP_FRAME = 1 };

struct c300x_rtsp_writer {
    pthread_mutex_t mutex;
    atomic_uint references;
    atomic_bool media_closed;
    /* Monotonic ms of the first dropped frame since the last sent one, 0 while frames go out. */
    atomic_llong stalled_since;
    unsigned char *tail;
    int wake_fd;
    atomic_llong tail_deadline;
    size_t tail_pos, tail_len;
};

struct c300x_rtsp_writer *c300x_rtsp_writer_create(void)
{
    struct c300x_rtsp_writer *writer = calloc(1, sizeof(*writer));
    if (writer == NULL) return NULL;
    if (pthread_mutex_init(&writer->mutex, NULL) != 0) {
        free(writer);
        return NULL;
    }
    atomic_init(&writer->references, 1);
    writer->wake_fd = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
    if (writer->wake_fd < 0) {
        pthread_mutex_destroy(&writer->mutex);
        free(writer);
        return NULL;
    }
    atomic_init(&writer->tail_deadline, 0);
    atomic_init(&writer->media_closed, false);
    atomic_init(&writer->stalled_since, 0);
    return writer;
}

void c300x_rtsp_writer_retain(struct c300x_rtsp_writer *writer)
{
    atomic_fetch_add_explicit(&writer->references, 1, memory_order_relaxed);
}

void c300x_rtsp_writer_end_media(struct c300x_rtsp_writer *writer)
{
    atomic_store(&writer->media_closed, true);
}

void c300x_rtsp_writer_release(struct c300x_rtsp_writer *writer)
{
    if (writer != NULL &&
        atomic_fetch_sub_explicit(&writer->references, 1, memory_order_acq_rel) == 1) {
        pthread_mutex_destroy(&writer->mutex);
        close(writer->wake_fd);
        free(writer->tail);
        free(writer);
    }
}

static int writer_lock(struct c300x_rtsp_writer *writer, long long deadline)
{
    if (writer == NULL) { errno = EINVAL; return 0; }
    for (;;) {
        int error = pthread_mutex_trylock(&writer->mutex);
        if (error == 0) return 1;
        if (error != EBUSY) { errno = error; return 0; }
        if (c300x_monotonic_ms() >= deadline) break;
        /* Avoid realtime timed-mutex deadlines on devices whose wall clock
         * can change. Lock contention consumes the same budget as the write. */
        struct timespec pause = {.tv_nsec = 1000000};
        nanosleep(&pause, NULL);
    }
    errno = ETIMEDOUT;
    return 0;
}

/* Bytes accepted on success or deadline; -1 only for a transport failure. */
static ssize_t send_pair_until(int fd, const void *first, size_t first_len,
                              const void *second, size_t second_len,
                              long long deadline)
{
    struct iovec iov[2];
    struct iovec *pending = iov;
    size_t count = 0, sent = 0;
    int attempted = 0;
    if (first_len) iov[count++] = (struct iovec){.iov_base = (void *)first, .iov_len = first_len};
    if (second_len) iov[count++] = (struct iovec){.iov_base = (void *)second, .iov_len = second_len};
    while (count > 0) {
        /* A stalled client still gets one nonblocking recovery attempt.
         * Every retry, including EINTR and short writes, shares the deadline. */
        if (attempted && c300x_monotonic_ms() >= deadline) {
            errno = ETIMEDOUT;
            return (ssize_t)sent;
        }
        attempted = 1;
        struct msghdr message = {.msg_iov = pending, .msg_iovlen = count};
        ssize_t n = sendmsg(fd, &message, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            if (c300x_rtsp_wait_writable(fd, deadline)) continue;
            return errno == ETIMEDOUT ? (ssize_t)sent : -1;
        }
        if (n <= 0) return -1;
        sent += (size_t)n;
        size_t advanced = (size_t)n;
        while (count > 0 && advanced >= pending[0].iov_len) {
            advanced -= pending[0].iov_len;
            pending++;
            count--;
        }
        if (count > 0 && advanced > 0) {
            pending[0].iov_base = (char *)pending[0].iov_base + advanced;
            pending[0].iov_len -= advanced;
        }
    }
    return sent == first_len + second_len ? (ssize_t)sent : -1;
}

/* A dropped frame leaves the stream whole. Only a connection that has taken
 * no frame for the stall limit is closed. */
static ssize_t frame_dropped(struct c300x_rtsp_writer *writer, int fd, long long now)
{
    long long since = 0;
    if (atomic_compare_exchange_strong(&writer->stalled_since, &since, now > 0 ? now : 1)) return 0;
    if (now - since < RTSP_STALL_LIMIT_MS) return 0;
    shutdown(fd, SHUT_RDWR);
    return -1;
}

/* The relay owns the input buffers only during this call. Copy just the
 * unsent suffix, including a split interleaved header when necessary. */
static int keep_tail(struct c300x_rtsp_writer *writer, const void *first, size_t first_len,
                     const void *second, size_t second_len, size_t sent)
{
    size_t left = first_len + second_len - sent;
    unsigned char *tail = malloc(left);
    if (!tail) return 0;
    size_t head = sent < first_len ? first_len - sent : 0;
    if (head) memcpy(tail, (const unsigned char *)first + sent, head);
    if (left > head) memcpy(tail + head, (const unsigned char *)second + (sent > first_len ? sent - first_len : 0),
                            left - head);
    writer->tail = tail;
    writer->tail_pos = 0;
    writer->tail_len = left;
    return 1;
}

/* Under the writer mutex: 1 drained, 0 still pending, -1 terminal. */
static int flush_tail(struct c300x_rtsp_writer *writer, int fd, long long limit)
{
    if (!writer->tail) return 1;
    long long expiry = atomic_load(&writer->tail_deadline);
    if (c300x_monotonic_ms() >= expiry) return -1;
    size_t left = writer->tail_len - writer->tail_pos;
    ssize_t n = send_pair_until(fd, writer->tail + writer->tail_pos, left, NULL, 0,
                                expiry < limit ? expiry : limit);
    if (n < 0) return -1;
    writer->tail_pos += (size_t)n;
    if ((size_t)n != left) return 0;
    free(writer->tail);
    writer->tail = NULL;
    atomic_store(&writer->tail_deadline, 0);
    atomic_store(&writer->stalled_since, 0);
    return 1;
}

/* limit: a frame's absolute deadline when sooner than its own budget, 0 for
 * none. */
static ssize_t writer_send_by(struct c300x_rtsp_writer *writer, int fd,
                              const void *first, size_t first_len,
                              const void *second, size_t second_len, enum rtsp_message kind,
                              long long limit)
{
    int frame = kind == RTSP_FRAME;
    if (frame && writer && atomic_load(&writer->media_closed)) return 0;
    long long now = c300x_monotonic_ms();
    /* A stalled connection gets no initial wait. Even partial recovery writes
     * remain bounded by the shared media budget for the other clients. */
    int wait_ms = !frame ? RTSP_RESPONSE_MS
        : (writer != NULL && atomic_load(&writer->stalled_since) ? 0 : RTSP_FRAME_WRITE_MS);
    long long start_deadline = now + wait_ms;
    if (frame && limit > 0 && limit < start_deadline) start_deadline = limit;
    if (!writer_lock(writer, start_deadline)) {
        if (frame && writer && atomic_load(&writer->media_closed)) return 0;
        if (frame && writer != NULL) return frame_dropped(writer, fd, c300x_monotonic_ms());
        shutdown(fd, SHUT_RDWR);
        return -1;
    }
    ssize_t result = -1;
    /* A retained target can acquire the mutex after the TEARDOWN response.
     * Check here, not just during slot lookup. Control writes still drain tail. */
    if (frame && atomic_load(&writer->media_closed)) {
        result = 0;
        goto done;
    }
    if (writer->tail) {
        int flushed = flush_tail(writer, fd, start_deadline);
        if (flushed < 0) goto broken;
        if (!flushed) {
            if (!frame) goto broken;
            result = frame_dropped(writer, fd, c300x_monotonic_ms());
            goto done;
        }
    }
    result = send_pair_until(fd, first, first_len, second, second_len, start_deadline);
    if (frame && result >= 0 && (size_t)result < first_len + second_len) {
        if (result && !keep_tail(writer, first, first_len, second, second_len, (size_t)result)) goto broken;
        result = frame_dropped(writer, fd, c300x_monotonic_ms());
        if (writer->tail && result == 0) {
            atomic_store(&writer->tail_deadline, atomic_load(&writer->stalled_since) + RTSP_STALL_LIMIT_MS);
            eventfd_t one = 1;
            ssize_t n;
            do { n = write(writer->wake_fd, &one, sizeof(one)); } while (n < 0 && errno == EINTR);
            if (n < 0 && errno != EAGAIN) goto broken;
        }
    } else if (result < 0 || (size_t)result != first_len + second_len) {
        goto broken;
    } else if (frame) {
        atomic_store(&writer->stalled_since, 0);
    }
    goto done;
broken:
    shutdown(fd, SHUT_RDWR);
    result = -1;
done:
    pthread_mutex_unlock(&writer->mutex);
    return result;
}

static ssize_t writer_send(struct c300x_rtsp_writer *writer, int fd,
                           const void *first, size_t first_len,
                           const void *second, size_t second_len, enum rtsp_message kind)
{
    return writer_send_by(writer, fd, first, first_len, second, second_len, kind, 0);
}

long long c300x_rtsp_deadline_in(int ms)
{
    return c300x_monotonic_ms() + ms;
}

ssize_t c300x_rtsp_send_pair_by(struct c300x_rtsp_writer *writer, int fd,
                               const void *first, size_t first_len,
                               const void *second, size_t second_len, long long deadline_ms)
{
    if (first_len > 65539 || second_len > 65539 - first_len) { errno = EMSGSIZE; return -1; }
    return writer_send_by(writer, fd, first, first_len, second, second_len, RTSP_FRAME, deadline_ms);
}

ssize_t c300x_rtsp_send_pair(struct c300x_rtsp_writer *writer, int fd,
                            const void *first, size_t first_len,
                            const void *second, size_t second_len)
{
    return c300x_rtsp_send_pair_by(writer, fd, first, first_len, second, second_len, 0);
}

ssize_t c300x_rtsp_send_interleaved(struct c300x_rtsp_writer *writer,
                                   int fd, int channel,
                                   const void *packet, size_t packet_len)
{
    unsigned char frame_header[4];
    frame_header[0] = '$';
    frame_header[1] = (unsigned char)channel;
    frame_header[2] = (unsigned char)((packet_len >> 8) & 0xff);
    frame_header[3] = (unsigned char)(packet_len & 0xff);
    return c300x_rtsp_send_pair(
        writer, fd, frame_header, sizeof(frame_header), packet, packet_len
    );
}

void c300x_rtsp_send_targets(const rtsp_send_target_t *targets, size_t count,
                             const void *packet, size_t packet_len)
{
    for (size_t index = 0; index < count; index++) {
        const rtsp_send_target_t *target = &targets[index];
        if (target->transport_tcp) {
            (void)c300x_rtsp_send_interleaved(
                target->writer, target->fd, target->channel, packet, packet_len
            );
        }
        close(target->fd);
        c300x_rtsp_writer_release(target->writer);
    }
}

int parse_interleaved_channel(const char *transport)
{
    const char *pos = strstr(transport, "interleaved=");
    char *end = NULL;
    long value;
    if (pos == NULL) {
        return -1;
    }
    value = strtol(pos + 12, &end, 10);
    /* The channel is one byte of the frame header and the answer prints the
     * next one as well: anything else counts as not given. */
    if (end == pos + 12 || value < 0 || value > 254) {
        return -1;
    }
    return (int)value;
}

int c300x_rtsp_connection_add(int fds[RTSP_CONNECTION_LIMIT], int fd)
{
    for (int index = 0; index < RTSP_CONNECTION_LIMIT; index++) {
        if (fds[index] == 0) {
            fds[index] = fd + 1;
            return index;
        }
    }
    return -1;
}

void c300x_rtsp_connections_shutdown(const int fds[RTSP_CONNECTION_LIMIT])
{
    for (int index = 0; index < RTSP_CONNECTION_LIMIT; index++) {
        if (fds[index] > 0) {
            shutdown(fds[index] - 1, SHUT_RDWR);
        }
    }
}

int c300x_rtsp_wait_writable(int fd, long long deadline_ms)
{
    for (;;) {
        long long remaining = deadline_ms - c300x_monotonic_ms();
        if (remaining <= 0) { errno = ETIMEDOUT; return 0; }
        struct pollfd pending = {.fd = fd, .events = POLLOUT};
        int result = poll(&pending, 1, remaining > INT_MAX ? INT_MAX : (int)remaining);
        if (result < 0 && errno == EINTR) continue;
        if (result == 0) errno = ETIMEDOUT;
        if (result <= 0) return 0;
        if ((pending.revents & (POLLERR | POLLHUP | POLLNVAL)) || !(pending.revents & POLLOUT)) {
            errno = EPIPE;
            return 0;
        }
        return 1;
    }
}

int c300x_rtsp_wait_readable(struct c300x_rtsp_writer *writer, int fd, int timeout_seconds,
                             long long deadline_ms)
{
    long long wait_until = c300x_monotonic_ms() + (long long)timeout_seconds * 1000LL;
    if (deadline_ms > 0 && deadline_ms < wait_until) wait_until = deadline_ms;
    for (;;) {
        long long now = c300x_monotonic_ms();
        if (now >= wait_until) return 0;
        long long expiry = writer ? atomic_load(&writer->tail_deadline) : 0;
        long long remaining = (expiry && expiry < wait_until ? expiry : wait_until) - now;
        struct pollfd pending[] = {
            {.fd = fd, .events = POLLIN | (expiry ? POLLOUT : 0)},
            {.fd = writer ? writer->wake_fd : -1, .events = POLLIN},
        };
        int result = poll(pending, writer ? 2 : 1,
                          remaining <= 0 ? 0 : remaining > INT_MAX ? INT_MAX : (int)remaining);
        if (result < 0 && errno == EINTR) continue;
        if (result < 0) return -1;
        if (pending[1].revents & POLLIN) {
            eventfd_t value;
            if (read(writer->wake_fd, &value, sizeof(value)) < 0 && errno != EINTR && errno != EAGAIN)
                return -1;
        }
        if (expiry && ((pending[0].revents & POLLOUT) || c300x_monotonic_ms() >= expiry)) {
            pthread_mutex_lock(&writer->mutex);
            int flushed = flush_tail(writer, fd, c300x_monotonic_ms());
            if (flushed < 0) shutdown(fd, SHUT_RDWR);
            pthread_mutex_unlock(&writer->mutex);
            if (flushed < 0) return -1;
        }
        if (pending[0].revents & (POLLIN | POLLHUP | POLLERR | POLLNVAL)) return 1;
    }
}

int c300x_rtsp_read_timeout(int teardown_seconds, int session_seconds, long long deadline_ms)
{
    int seconds = teardown_seconds > 0 ? teardown_seconds
        : (session_seconds > 0 ? session_seconds : 30);
    if (deadline_ms > 0) {
        long long remaining_ms = deadline_ms - c300x_monotonic_ms();
        if (remaining_ms <= 0) return 0;
        long long remaining_seconds = (remaining_ms + 999) / 1000;
        if (remaining_seconds < seconds) seconds = (int)remaining_seconds;
    }
    return seconds;
}

void send_rtsp_response(
    struct c300x_rtsp_writer *writer,
    int fd,
    int status,
    const char *cseq,
    const char *headers,
    const char *body
) {
    const char *status_text = status == 200 ? "OK" :
        (status == 401 ? "Unauthorized" : (status == 461 ? "Unsupported Transport" : "Error"));
    size_t body_len = body ? strlen(body) : 0;
    char response[4096];
    int n = snprintf(
        response,
        sizeof(response),
        "RTSP/1.0 %d %s\r\n"
        "CSeq: %s\r\n"
        "%s"
        "Content-Length: %zu\r\n"
        "\r\n"
        "%s",
        status,
        status_text,
        cseq && cseq[0] ? cseq : "1",
        headers ? headers : "",
        body_len,
        body ? body : ""
    );
    if (n > 0 && n < (int)sizeof(response)) {
        (void)writer_send(writer, fd, response, (size_t)n, NULL, 0, RTSP_RESPONSE);
    }
}
