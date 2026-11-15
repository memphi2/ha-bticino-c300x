#include "media_rtsp_io.h"
#include "time_util.h"

#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <time.h>

struct c300x_rtsp_writer {
    pthread_mutex_t mutex;
    atomic_uint references;
};

struct c300x_rtsp_writer *c300x_rtsp_writer_create(void)
{
    struct c300x_rtsp_writer *writer = malloc(sizeof(*writer));
    if (writer == NULL) return NULL;
    if (pthread_mutex_init(&writer->mutex, NULL) != 0) {
        free(writer);
        return NULL;
    }
    atomic_init(&writer->references, 1);
    return writer;
}

void c300x_rtsp_writer_retain(struct c300x_rtsp_writer *writer)
{
    atomic_fetch_add_explicit(&writer->references, 1, memory_order_relaxed);
}

void c300x_rtsp_writer_release(struct c300x_rtsp_writer *writer)
{
    if (writer != NULL &&
        atomic_fetch_sub_explicit(&writer->references, 1, memory_order_acq_rel) == 1) {
        pthread_mutex_destroy(&writer->mutex);
        free(writer);
    }
}

static int writer_lock(struct c300x_rtsp_writer *writer, long long deadline)
{
    if (writer == NULL) { errno = EINVAL; return 0; }
    while (c300x_monotonic_ms() < deadline) {
        int error = pthread_mutex_trylock(&writer->mutex);
        if (error == 0) return 1;
        if (error != EBUSY) { errno = error; return 0; }
        /* Avoid realtime timed-mutex deadlines on devices whose wall clock
         * can change. Lock contention consumes the same budget as the write. */
        struct timespec pause = {.tv_nsec = 1000000};
        nanosleep(&pause, NULL);
    }
    errno = ETIMEDOUT;
    return 0;
}

static ssize_t send_pair_until(int fd, const void *first, size_t first_len,
                              const void *second, size_t second_len, long long deadline)
{
    struct iovec iov[2];
    struct iovec *pending = iov;
    size_t count = 0, sent = 0;
    if (first_len) iov[count++] = (struct iovec){.iov_base = (void *)first, .iov_len = first_len};
    if (second_len) iov[count++] = (struct iovec){.iov_base = (void *)second, .iov_len = second_len};
    while (count > 0) {
        struct msghdr message = {.msg_iov = pending, .msg_iovlen = count};
        if (!c300x_rtsp_wait_writable(fd, deadline)) return -1;
        ssize_t n = sendmsg(fd, &message, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) continue;
        if (n <= 0) return n;
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

static ssize_t writer_send(struct c300x_rtsp_writer *writer, int fd,
                           const void *first, size_t first_len,
                           const void *second, size_t second_len, int timeout_ms)
{
    long long deadline = c300x_monotonic_ms() + timeout_ms;
    if (!writer_lock(writer, deadline)) {
        shutdown(fd, SHUT_RDWR);
        return -1;
    }
    ssize_t result = send_pair_until(fd, first, first_len, second, second_len, deadline);
    /* A partially written frame/response must never be followed by another
     * message on this stream. Shutdown is safe on the retained socket. */
    if (result < 0 || (size_t)result != first_len + second_len) shutdown(fd, SHUT_RDWR);
    pthread_mutex_unlock(&writer->mutex);
    return result;
}

ssize_t c300x_rtsp_send_pair(struct c300x_rtsp_writer *writer, int fd,
                            const void *first, size_t first_len,
                            const void *second, size_t second_len)
{
    return writer_send(writer, fd, first, first_len, second, second_len, 250);
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
        if (result <= 0) return 0;
        return (pending.revents & (POLLERR | POLLHUP | POLLNVAL)) == 0 &&
               (pending.revents & POLLOUT) != 0;
    }
}

int c300x_rtsp_wait_readable(int fd, int timeout_seconds, long long deadline_ms)
{
    long long wait_until = c300x_monotonic_ms() + (long long)timeout_seconds * 1000LL;
    if (deadline_ms > 0 && deadline_ms < wait_until) wait_until = deadline_ms;
    for (;;) {
        long long remaining = wait_until - c300x_monotonic_ms();
        if (remaining <= 0) return 0;
        struct pollfd pending = {.fd = fd, .events = POLLIN};
        int result = poll(&pending, 1, remaining > INT_MAX ? INT_MAX : (int)remaining);
        if (result < 0 && errno == EINTR) continue;
        if (result <= 0) return result;
        return 1;
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
        (void)writer_send(writer, fd, response, (size_t)n, NULL, 0, 2000);
    }
}
