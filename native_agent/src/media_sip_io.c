#include "media_sip_io.h"

#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdbool.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <time.h>

#define SIP_READ_TIMEOUT (-2)
#define SIP_READ_KEEPALIVE (-3)

static long long monotonic_ms(void)
{
    struct timespec now;

    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        return -1;
    }
    return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static ssize_t receive_until(int fd, void *buffer, size_t size, int flags, long long deadline)
{
    for (;;) {
        long long now = monotonic_ms();
        struct pollfd socket = {.fd = fd, .events = POLLIN};
        int ready;
        ssize_t count;

        if (now < 0) {
            return -1;
        }
        if (now >= deadline) {
            return SIP_READ_TIMEOUT;
        }
        ready = poll(&socket, 1, (int)(deadline - now));
        if (ready == 0) {
            return SIP_READ_TIMEOUT;
        }
        if (ready < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        count = recv(fd, buffer, size, flags | MSG_DONTWAIT);
        if (count < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) {
            continue;
        }
        return count;
    }
}

static bool is_lws(char value)
{
    return value == ' ' || value == '\t' || value == '\r' || value == '\n';
}

static bool message_length(
    const char *buffer, size_t header_size, size_t limit, bool stream, size_t *length
)
{
    const char *header_end = buffer + header_size - 2;
    const char *line = strstr(buffer, "\r\n");
    bool found = false;

    if (line == NULL) {
        return false;
    }
    line += 2;
    while (line < header_end) {
        const char *end = strstr(line, "\r\n");
        const char *colon = memchr(line, ':', (size_t)(end - line));
        const char *name_end = colon;

        while (end + 2 < header_end && (end[2] == ' ' || end[2] == '\t')) {
            end = strstr(end + 2, "\r\n");
        }
        if (colon != NULL) {
            while (name_end > line && (name_end[-1] == ' ' || name_end[-1] == '\t')) {
                name_end--;
            }
            size_t name_size = (size_t)(name_end - line);
            if ((name_size == 14 && strncasecmp(line, "Content-Length", 14) == 0)
                || (name_size == 1 && (*line == 'l' || *line == 'L'))) {
                const char *value = colon + 1;
                size_t body_size = 0;
                size_t maximum = limit - header_size;

                if (found) {
                    return false;
                }
                while (value < end && is_lws(*value)) {
                    value++;
                }
                if (value == end || *value < '0' || *value > '9') {
                    return false;
                }
                while (value < end && *value >= '0' && *value <= '9') {
                    unsigned digit = (unsigned)(*value++ - '0');
                    if (body_size > maximum / 10
                        || (body_size == maximum / 10 && digit > maximum % 10)) {
                        return false;
                    }
                    body_size = body_size * 10 + digit;
                }
                while (value < end && is_lws(*value)) {
                    value++;
                }
                if (value != end) {
                    return false;
                }
                *length = header_size + body_size;
                found = true;
            }
        }
        line = end + 2;
    }
    if (!found) {
        *length = limit;
    }
    return found || !stream;
}

static int read_datagram(int fd, char *buffer, size_t limit, long long deadline)
{
    ssize_t count = receive_until(fd, buffer, limit, MSG_TRUNC, deadline);
    size_t length;
    size_t leading = 0;
    char *end;

    if (count == SIP_READ_TIMEOUT) {
        return 0;
    }
    if (count <= 0 || (size_t)count > limit) {
        return -1;
    }
    buffer[count] = '\0';
    while (leading + 2 <= (size_t)count && memcmp(buffer + leading, "\r\n", 2) == 0) {
        leading += 2;
    }
    count -= (ssize_t)leading;
    memmove(buffer, buffer + leading, (size_t)count + 1);
    if (count == 0) {
        return SIP_READ_KEEPALIVE;
    }
    end = strstr(buffer, "\r\n\r\n");
    if (end == NULL
        || !message_length(buffer, (size_t)(end + 4 - buffer), (size_t)count, false, &length)) {
        return -1;
    }
    buffer[length] = '\0';
    return (int)length;
}

static int read_stream(
    int fd, char *buffer, size_t limit, long long deadline, bool wait_after_keepalive
)
{
    size_t used = 0;
    size_t length = 0;

    while (used < limit) {
        size_t take = length != 0 ? length - used : limit - used;
        bool keepalive = false;
        ssize_t count;

        if (length == 0) {
            /* Peek only to locate the frame boundary. Consume no bytes belonging
             * to the next SIP message, so select() still sees it on the socket. */
            count = receive_until(fd, buffer + used, take, MSG_PEEK, deadline);
            if (count == SIP_READ_TIMEOUT) {
                return used == 0 ? 0 : -1;
            }
            if (count <= 0) {
                return -1;
            }
            buffer[used + (size_t)count] = '\0';
            take = (size_t)count;
            if (buffer[0] == '\r') {
                if (used + take >= 2) {
                    if (buffer[1] != '\n') {
                        return -1;
                    }
                    take = 2 - used;
                    keepalive = true;
                }
            } else {
                char *end = strstr(buffer, "\r\n\r\n");
                if (end != NULL) {
                    size_t header_size = (size_t)(end + 4 - buffer);
                    if (!message_length(buffer, header_size, limit, true, &length)) {
                        return -1;
                    }
                    take = header_size - used;
                }
            }
        }
        count = receive_until(fd, buffer + used, take, 0, deadline);
        if (count <= 0) {
            return -1;
        }
        used += (size_t)count;
        buffer[used] = '\0';
        if (keepalive && used == 2) {
            used = 0;
            buffer[0] = '\0';
            if (!wait_after_keepalive) {
                struct pollfd socket = {.fd = fd, .events = POLLIN};
                int ready = poll(&socket, 1, 0);
                if (ready == 0 || (ready < 0 && errno == EINTR)) {
                    return 0;
                }
                if (ready < 0) {
                    return -1;
                }
            }
        } else if (length != 0 && used == length) {
            return (int)used;
        }
    }
    return -1;
}

static int read_socket_message(
    int fd, char *buffer, size_t capacity, int timeout_ms, bool wait_after_keepalive
)
{
    int type;
    socklen_t type_size = sizeof(type);
    long long now;
    int result;

    if (buffer == NULL || capacity == 0) {
        return -1;
    }
    buffer[0] = '\0';
    if (fd < 0 || capacity < 5 || capacity > INT_MAX || timeout_ms <= 0
        || getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &type_size) != 0) {
        return -1;
    }
    now = monotonic_ms();
    if (now < 0) {
        return -1;
    }
    if (type == SOCK_DGRAM) {
        do {
            result = read_datagram(fd, buffer, capacity - 1, now + timeout_ms);
        } while (result == SIP_READ_KEEPALIVE && wait_after_keepalive);
        if (result == SIP_READ_KEEPALIVE) {
            result = 0;
        }
    } else if (type == SOCK_STREAM) {
        result = read_stream(fd, buffer, capacity - 1, now + timeout_ms, wait_after_keepalive);
    } else {
        result = -1;
    }
    if (result <= 0) {
        buffer[0] = '\0';
    }
    return result;
}

int c300x_media_sip_read_message(int fd, char *buffer, size_t capacity, int timeout_ms)
{
    return read_socket_message(fd, buffer, capacity, timeout_ms, true);
}

int c300x_media_sip_poll_message(int fd, char *buffer, size_t capacity, int timeout_ms)
{
    return read_socket_message(fd, buffer, capacity, timeout_ms, false);
}
