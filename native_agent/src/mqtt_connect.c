#include "mqtt_connect.h"
#include "http_util.h"
#include "openwebnet_waiters.h"

#include <errno.h>
#include <netdb.h>
#include <poll.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

#include "pthread_compat.h"

#define MQTT_CONNECT_TIMEOUT_MS 1500

enum { ATTEMPT_RUNNING, ATTEMPT_DONE, ATTEMPT_CANCELLED };

struct c300x_mqtt_connect {
    atomic_int state;
    int fd;
    int wake[2];
    uint16_t port;
    char host[256];
};

static int set_nonblocking(int fd)
{
    int enabled = 1;
    return ioctl(fd, FIONBIO, &enabled) == 0;
}

static int socket_connect_timeout(const char *host, uint16_t port)
{
    char port_text[16];
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    struct addrinfo *item;
    int fd = -1;

    snprintf(port_text, sizeof(port_text), "%u", port);
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(host, port_text, &hints, &result) != 0) {
        return -1;
    }
    for (item = result; item != NULL; item = item->ai_next) {
        int err = 0;
        socklen_t err_len = sizeof(err);
        struct pollfd pfd;
        fd = socket(item->ai_family, item->ai_socktype, item->ai_protocol);
        if (fd < 0) {
            continue;
        }
        set_fd_cloexec(fd);
        if (!set_nonblocking(fd)) {
            close(fd);
            fd = -1;
            continue;
        }
        if (connect(fd, item->ai_addr, item->ai_addrlen) == 0) {
            break;
        }
        if (errno != EINPROGRESS) {
            close(fd);
            fd = -1;
            continue;
        }
        pfd.fd = fd;
        pfd.events = POLLOUT;
        pfd.revents = 0;
        if (poll(&pfd, 1, MQTT_CONNECT_TIMEOUT_MS) <= 0) {
            close(fd);
            fd = -1;
            continue;
        }
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &err_len) != 0 || err != 0) {
            close(fd);
            fd = -1;
            continue;
        }
        break;
    }
    freeaddrinfo(result);
    return fd;
}

static void attempt_free(struct c300x_mqtt_connect *attempt)
{
    if (attempt->fd >= 0) {
        close(attempt->fd);
    }
    close(attempt->wake[0]);
    close(attempt->wake[1]);
    free(attempt);
}

static void *attempt_run(void *context)
{
    struct c300x_mqtt_connect *attempt = context;
    char done = 1;
    int expected = ATTEMPT_RUNNING;

    attempt->fd = socket_connect_timeout(attempt->host, attempt->port);
    /* The byte comes first: once the state says done, the loop owns the
     * attempt and may free it at any time. */
    while (write(attempt->wake[1], &done, 1) < 0 && errno == EINTR) {
    }
    if (!atomic_compare_exchange_strong(&attempt->state, &expected, ATTEMPT_DONE)) {
        attempt_free(attempt);
    }
    return NULL;
}

struct c300x_mqtt_connect *c300x_mqtt_connect_start(const char *host, uint16_t port)
{
    struct c300x_mqtt_connect *attempt = calloc(1, sizeof(*attempt));
    pthread_attr_t attr;
    pthread_t thread;
    int started;

    if (attempt == NULL || strlen(host) >= sizeof(attempt->host)) {
        free(attempt);
        return NULL;
    }
    if (!c300x_openwebnet_wake_pipe(attempt->wake)) {
        free(attempt);
        return NULL;
    }
    atomic_init(&attempt->state, ATTEMPT_RUNNING);
    attempt->fd = -1;
    attempt->port = port;
    memcpy(attempt->host, host, strlen(host) + 1);
    if (pthread_attr_init(&attr) != 0) {
        attempt_free(attempt);
        return NULL;
    }
    (void)pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    started = pthread_create(&thread, &attr, attempt_run, attempt) == 0;
    (void)pthread_attr_destroy(&attr);
    if (!started) {
        attempt_free(attempt);
        return NULL;
    }
    return attempt;
}

int c300x_mqtt_connect_wake_fd(const struct c300x_mqtt_connect *attempt)
{
    return attempt != NULL ? attempt->wake[0] : -1;
}

int c300x_mqtt_connect_finish(struct c300x_mqtt_connect *attempt)
{
    int fd;

    if (attempt == NULL || atomic_load(&attempt->state) != ATTEMPT_DONE) {
        return -2;
    }
    fd = attempt->fd;
    attempt->fd = -1;
    attempt_free(attempt);
    return fd;
}

void c300x_mqtt_connect_cancel(struct c300x_mqtt_connect *attempt)
{
    int expected = ATTEMPT_RUNNING;

    if (attempt != NULL && !atomic_compare_exchange_strong(&attempt->state, &expected, ATTEMPT_CANCELLED)) {
        attempt_free(attempt);
    }
}
