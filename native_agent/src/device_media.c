#define _POSIX_C_SOURCE 200809L

#include "device_media.h"

#include "c300x_agent.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define DEVICE_MEDIA_PORT 30007
#define DEVICE_MEDIA_COMMAND_TIMEOUT_MS 2000
#define DEVICE_MEDIA_TAKEOVER_SETTLE_MS 800

static int video_rtp_port(const struct c300x_config *config) {
    return (int)config->video_rtp_port_start + 2;
}

static int audio_rtp_port(const struct c300x_config *config) {
    return (int)config->video_rtp_port_start;
}

static long long monotonic_ms(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return -1;
    return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static bool wait_socket(int fd, short events, long long deadline) {
    for (;;) {
        long long now = monotonic_ms();
        if (now < 0 || now >= deadline) return false;
        struct pollfd pending = {.fd = fd, .events = events};
        int ready = poll(&pending, 1, (int)(deadline - now));
        if (ready < 0 && errno == EINTR) continue;
        /* POLLIN may accompany HUP when the peer sends its final reply. */
        return ready > 0 && !(pending.revents & (POLLERR | POLLNVAL))
            && (pending.revents & events) != 0;
    }
}

static ssize_t send_all(int fd, const void *buf, size_t len, long long deadline) {
    const char *p = buf;
    size_t left = len;
    while (left > 0) {
        if (!wait_socket(fd, POLLOUT, deadline)) return -1;
        ssize_t n = send(fd, p, left, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) continue;
        if (n <= 0) {
            return n;
        }
        p += n;
        left -= (size_t)n;
    }
    return (ssize_t)len;
}

static int connect_local_tcp(int port, long long deadline) {
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) {
        return -1;
    }

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr) != 1) {
        close(fd);
        return -1;
    }

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        if ((errno != EINPROGRESS && errno != EINTR)
            || !wait_socket(fd, POLLOUT, deadline)) {
            close(fd);
            return -1;
        }
        int error = 0;
        socklen_t size = sizeof(error);
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &size) != 0 || error != 0) {
            close(fd);
            return -1;
        }
    }
    return fd;
}

static bool send_device_media_command(const char *command, char *reply, size_t reply_len) {
    if (reply_len == 0) return false;
    reply[0] = '\0';
    long long now = monotonic_ms();
    if (now < 0) return false;
    /* Retries and partial writes share the command's original deadline. */
    long long deadline = now + DEVICE_MEDIA_COMMAND_TIMEOUT_MS;
    int fd = connect_local_tcp(DEVICE_MEDIA_PORT, deadline);
    if (fd < 0) {
        return false;
    }
    bool ok = false;
    if (send_all(fd, command, strlen(command), deadline) > 0) {
        size_t used = 0;
        while (used + 1 < reply_len && wait_socket(fd, POLLIN, deadline)) {
            ssize_t n = recv(fd, reply + used, reply_len - used - 1, MSG_DONTWAIT);
            if (n < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) continue;
            if (n <= 0) break;
            used += (size_t)n;
            reply[used] = '\0';
            if (strstr(reply, "##") != NULL) {
                ok = strstr(reply, "*#*1##") != NULL;
                break;
            }
        }
    }
    close(fd);
    return ok;
}

static void sleep_ms(long milliseconds) {
    if (milliseconds <= 0) {
        return;
    }
    struct timespec delay = {
        .tv_sec = milliseconds / 1000,
        .tv_nsec = (milliseconds % 1000) * 1000000L,
    };
    (void)nanosleep(&delay, NULL);
}

bool c300x_device_media_start(const struct c300x_config *config) {
    if (config == NULL) {
        return false;
    }
    char command[128];
    char reply[128] = {0};
    int quality = config->video_av_high_resolution ? 0 : 1;
    snprintf(
        command,
        sizeof(command),
        "*7*300#127#0#0#1#%d#%d*##",
        video_rtp_port(config),
        quality
    );
    if (!send_device_media_command(command, reply, sizeof(reply))) {
        return false;
    }

    struct timespec audio_delay = {0, 300000000L};
    (void)nanosleep(&audio_delay, NULL);
    snprintf(
        command,
        sizeof(command),
        "*7*300#127#0#0#1#%d#2*##",
        audio_rtp_port(config)
    );
    (void)send_device_media_command(command, reply, sizeof(reply));
    return true;
}

void c300x_device_media_stop(const struct c300x_config *config) {
    if (config == NULL) {
        return;
    }

    char command[128];
    char reply[128] = {0};
    int quality = config->video_av_high_resolution ? 0 : 1;

    snprintf(
        command,
        sizeof(command),
        "*7*301#127#0#0#1#%d#2*##",
        audio_rtp_port(config)
    );
    /* Detach our own clients. A NACK can also mean SIP BYE already removed the
       pipeline; neither an ACK nor a NACK establishes device teardown health. */
    if (!send_device_media_command(command, reply, sizeof(reply))) {
        fprintf(stderr, "device-media: audio client removal not acknowledged (port %d, %s)\n",
                audio_rtp_port(config), strstr(reply, "*#*0##") != NULL ? "NACK" : "no ACK");
    }

    snprintf(
        command,
        sizeof(command),
        "*7*301#127#0#0#1#%d#%d*##",
        video_rtp_port(config),
        quality
    );
    if (!send_device_media_command(command, reply, sizeof(reply))) {
        fprintf(stderr, "device-media: video client removal not acknowledged (port %d, %s)\n",
                video_rtp_port(config), strstr(reply, "*#*0##") != NULL ? "NACK" : "no ACK");
    }
}

bool c300x_device_media_takeover(const struct c300x_config *config) {
    if (config == NULL) {
        return false;
    }
    bool started = c300x_device_media_start(config);
    sleep_ms(DEVICE_MEDIA_TAKEOVER_SETTLE_MS);
    /* SIP setup queues stock media-service fanout ports asynchronously. Do not
       send a media stop here: it tears down the just-opened media window and
       makes the following custom-port start return a media-service NACK. */
    return c300x_device_media_start(config) || started;
}
