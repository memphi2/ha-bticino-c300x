#define _POSIX_C_SOURCE 200809L

#include "media_bt_av.h"

#include "c300x_agent.h"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define BT_AV_MEDIA_PORT 30007
#define BT_AV_TAKEOVER_SETTLE_MS 800

static int video_rtp_port(const struct c300x_config *config) {
    return (int)config->video_rtp_port_start + 2;
}

static int audio_rtp_port(const struct c300x_config *config) {
    return (int)config->video_rtp_port_start;
}

static ssize_t send_all(int fd, const void *buf, size_t len) {
    const char *p = buf;
    size_t left = len;
    while (left > 0) {
        ssize_t n = send(fd, p, left, MSG_NOSIGNAL);
        if (n <= 0) {
            return n;
        }
        p += n;
        left -= (size_t)n;
    }
    return (ssize_t)len;
}

static int connect_local_tcp(int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
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
        close(fd);
        return -1;
    }
    return fd;
}

static bool send_bt_av_media_command(const char *command, char *reply, size_t reply_len) {
    int fd = connect_local_tcp(BT_AV_MEDIA_PORT);
    if (fd < 0) {
        return false;
    }
    bool ok = false;
    if (send_all(fd, command, strlen(command)) > 0) {
        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(fd, &readfds);
        struct timeval timeout = {2, 0};
        if (select(fd + 1, &readfds, NULL, NULL, &timeout) > 0) {
            ssize_t n = recv(fd, reply, reply_len - 1, 0);
            if (n > 0) {
                reply[n] = '\0';
                ok = strstr(reply, "*#*1##") != NULL;
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

bool c300x_media_bt_av_start(const struct c300x_config *config) {
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
    if (!send_bt_av_media_command(command, reply, sizeof(reply))) {
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
    (void)send_bt_av_media_command(command, reply, sizeof(reply));
    return true;
}

void c300x_media_bt_av_stop(void) {
    char reply[128] = {0};
    (void)send_bt_av_media_command("*7*0*##", reply, sizeof(reply));
}

bool c300x_media_bt_av_takeover(const struct c300x_config *config) {
    if (config == NULL) {
        return false;
    }
    bool started = c300x_media_bt_av_start(config);
    sleep_ms(BT_AV_TAKEOVER_SETTLE_MS);
    /* SIP setup queues stock BT-AV fanout ports asynchronously. Do not send a
       media stop here: it tears down the just-opened media window and makes
       the following custom-port start return a BT-AV NACK. */
    return c300x_media_bt_av_start(config) || started;
}
