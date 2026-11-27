/* All socket and clock operations are simulated: no device or network access. */
#include <assert.h>
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static int fake_socket(int, int, int);
static int fake_connect(int, const struct sockaddr *, socklen_t);
static int fake_getsockopt(int, int, int, void *, socklen_t *);
static int fake_poll(struct pollfd *, nfds_t, int);
static ssize_t fake_send(int, const void *, size_t, int);
static ssize_t fake_recv(int, void *, size_t, int);
static int fake_close(int);
static int fake_clock(clockid_t, struct timespec *);
static int fake_sleep(const struct timespec *, struct timespec *);
#define socket fake_socket
#define connect fake_connect
#define getsockopt fake_getsockopt
#define poll fake_poll
#define send fake_send
#define recv fake_recv
#define close fake_close
#define clock_gettime fake_clock
#define nanosleep fake_sleep
#undef _POSIX_C_SOURCE
#include "../src/device_media.c"
#undef socket
#undef connect
#undef getsockopt
#undef poll
#undef send
#undef recv
#undef close
#undef clock_gettime
#undef nanosleep

enum scenario {SUCCESS, CONNECT_TIMEOUT, CONNECT_ERROR, SEND_TIMEOUT, READ_TIMEOUT,
               INTERRUPTED, RETRIES, NACK, CLOCK_ERROR, SOCKET_ERROR, POLL_ERROR,
               SEND_ERROR, READ_ERROR, OPTION_ERROR, FRAGMENT_ACK, FRAGMENT_NACK,
               FRAGMENT_TIMEOUT, REPLY_FULL, READ_EOF, TAKEOVER_EARLY, TAKEOVER_LATE,
               TAKEOVER_NEVER, TAKEOVER_REFUSED, TAKEOVER_CANCELLED};
static enum scenario scenario;
static long long elapsed, opened_at;
static int opened, closed, polls, phase, sends, reads, command_count;
static char command[128], commands[8][128];
static size_t used;

static int fake_socket(int family, int type, int protocol) {
    assert(family == AF_INET && protocol == 0);
    assert(type == (SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC));
    if (scenario == SOCKET_ERROR) { errno = EMFILE; return -1; }
    assert(opened == closed);
    opened++;
    opened_at = elapsed;
    phase = 0;
    used = 0;
    sends = reads = 0;
    return 42;
}
static int fake_connect(int fd, const struct sockaddr *address, socklen_t size) {
    assert(fd == 42 && size == sizeof(struct sockaddr_in));
    const struct sockaddr_in *ipv4 = (const struct sockaddr_in *)address;
    assert(ntohs(ipv4->sin_port) == 30007);
    assert(ntohl(ipv4->sin_addr.s_addr) == INADDR_LOOPBACK);
    errno = EINPROGRESS;
    return -1;
}
static int fake_getsockopt(int fd, int level, int option, void *value, socklen_t *size) {
    assert(fd == 42 && level == SOL_SOCKET && option == SO_ERROR && *size == sizeof(int));
    if (scenario == OPTION_ERROR) { errno = EIO; return -1; }
    *(int *)value = scenario == CONNECT_ERROR ? ECONNREFUSED : 0;
    phase = 1;
    return 0;
}
static int fake_poll(struct pollfd *fds, nfds_t count, int timeout) {
    assert(count == 1 && fds->fd == 42 && timeout > 0);
    assert(timeout == DEVICE_MEDIA_COMMAND_TIMEOUT_MS - (elapsed - opened_at));
    assert(++polls < 100);
    if (scenario == POLL_ERROR) { fds->revents = POLLNVAL; return 1; }
    if ((scenario == CONNECT_TIMEOUT && phase == 0)
        || (scenario == SEND_TIMEOUT && phase == 1)
        || (scenario == READ_TIMEOUT && fds->events == POLLIN)
        || (scenario == FRAGMENT_TIMEOUT && reads == 3)) {
        elapsed += timeout;
        return 0;
    }
    elapsed += timeout < 100 ? timeout : 100;
    if (scenario == INTERRUPTED) { errno = EINTR; return -1; }
    fds->revents = fds->events | (fds->events == POLLIN ? POLLHUP : 0);
    return 1;
}
static ssize_t fake_send(int fd, const void *data, size_t len, int flags) {
    assert(fd == 42 && flags == (MSG_NOSIGNAL | MSG_DONTWAIT));
    sends++;
    if (scenario == SEND_ERROR) { errno = EPIPE; return -1; }
    if (scenario == RETRIES && sends <= 2) {
        errno = sends == 1 ? EINTR : EAGAIN;
        return -1;
    }
    size_t take = scenario == RETRIES && len > 10 ? 10 : len;
    assert(used + take < sizeof(command));
    memcpy(command + used, data, take);
    used += take;
    command[used] = '\0';
    return (ssize_t)take;
}
static ssize_t fake_recv(int fd, void *data, size_t len, int flags) {
    assert(fd == 42 && flags == MSG_DONTWAIT && len > 0);
    reads++;
    if (scenario == READ_EOF) return 0;
    if (scenario == REPLY_FULL) { memset(data, 'x', len); return (ssize_t)len; }
    if (scenario == FRAGMENT_ACK || scenario == FRAGMENT_NACK || scenario == FRAGMENT_TIMEOUT) {
        const char *response = scenario == FRAGMENT_NACK ? "*#*0##" : "*#*1##";
        assert(reads <= 6);
        *(char *)data = response[reads - 1];
        return 1;
    }
    if (scenario == READ_ERROR) { errno = ECONNRESET; return -1; }
    if (scenario == RETRIES && reads <= 2) {
        errno = reads == 1 ? EINTR : EAGAIN;
        return -1;
    }
    assert(command_count < 8);
    strcpy(commands[command_count++], command);
    /* No stream: the station refuses the client it already has. */
    bool refused = scenario == NACK || scenario == TAKEOVER_REFUSED
        || (scenario == TAKEOVER_NEVER && command_count > 1 && strstr(command, "#2*##") == NULL);
    memcpy(data, refused ? "*#*0##" : "*#*1##", 6);
    return 6;
}
static int fake_close(int fd) {
    assert(fd == 42 && closed < opened);
    closed++;
    return 0;
}
static int fake_clock(clockid_t clock, struct timespec *out) {
    assert(clock == CLOCK_MONOTONIC);
    if (scenario == CLOCK_ERROR) return -1;
    out->tv_sec = (time_t)(elapsed / 1000);
    out->tv_nsec = (long)(elapsed % 1000) * 1000000;
    return 0;
}
static int fake_sleep(const struct timespec *delay, struct timespec *remaining) {
    (void)remaining;
    elapsed += delay->tv_sec * 1000 + delay->tv_nsec / 1000000;
    return 0;
}
/* The station's stream on the agent's port, by scenario: there at the first
 * look, at the second, never, or the start is cancelled. Each command takes
 * 300 ms of simulated time (three polls). */
static int waits, wait_timeouts[8];
static int fake_wait(void *context, int timeout_ms) {
    assert(context == &waits && timeout_ms > 0 && waits < 8);
    wait_timeouts[waits++] = timeout_ms;
    if (scenario == TAKEOVER_EARLY || (scenario == TAKEOVER_LATE && waits == 2)) return 1;
    if (scenario == TAKEOVER_CANCELLED) return -1;
    elapsed += timeout_ms;
    return 0;
}

static void takeover(void) {
    static const char video[] = "*7*300#127#0#0#1#5002#1*##";
    static const char audio[] = "*7*300#127#0#0#1#5000#2*##";
    struct c300x_config config = {0};
    config.video_rtp_port_start = 5000;
    bool started = c300x_device_media_takeover(&config, fake_wait, &waits);
    assert(opened == command_count && closed == opened);
    for (int index = 0; index < command_count - 1; index++) assert(strcmp(commands[index], video) == 0);
    switch (scenario) {
    case TAKEOVER_EARLY:
        /* No fixed wait: the audio client follows the stream at once. */
        assert(started && command_count == 2 && strcmp(commands[1], audio) == 0);
        assert(waits == 1 && wait_timeouts[0] == 400 && elapsed == 600);
        break;
    case TAKEOVER_LATE:
        /* No stream 0.4 s after an accepted add: the client is added again. */
        assert(started && command_count == 3 && strcmp(commands[2], audio) == 0);
        assert(waits == 2 && wait_timeouts[0] == 400 && wait_timeouts[1] == 400 && elapsed == 1300);
        break;
    case TAKEOVER_NEVER:
        /* The stream never comes: the accepted client is refused as already
         * there, re-added every 0.4 s, and after 1.5 s it stands. */
        assert(started && command_count == 4 && strcmp(commands[3], audio) == 0);
        assert(waits == 2 && wait_timeouts[0] == 400 && wait_timeouts[1] == 400 && elapsed == 2000);
        break;
    case TAKEOVER_REFUSED:
        /* Refused adds are retried after 0.1 s, never followed by audio. */
        assert(!started && command_count == 4 && strcmp(commands[3], video) == 0);
        assert(waits == 3 && wait_timeouts[0] == 100 && wait_timeouts[2] == 100 && elapsed == 1500);
        break;
    case TAKEOVER_CANCELLED:
        /* The accepted client is reported so the caller removes it. */
        assert(started && command_count == 1 && waits == 1 && elapsed == 300);
        break;
    default:
        assert(!"unknown takeover scenario");
    }
    assert(c300x_device_media_takeover(&config, NULL, &waits) == false);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    scenario = (enum scenario)atoi(argv[1]);
    char reply[128];
    if (scenario >= TAKEOVER_EARLY) {
        takeover();
        return 0;
    }
    if (scenario != SUCCESS) {
        bool ok = send_device_media_command("*7*300#127#0#0#1#5002#0*##", reply, sizeof(reply));
        assert(ok == (scenario == RETRIES || scenario == FRAGMENT_ACK));
        assert(opened == closed && elapsed <= DEVICE_MEDIA_COMMAND_TIMEOUT_MS);
        if (scenario == CONNECT_TIMEOUT || scenario == SEND_TIMEOUT
            || scenario == READ_TIMEOUT || scenario == INTERRUPTED
            || scenario == FRAGMENT_TIMEOUT) assert(elapsed == 2000);
        if (scenario == FRAGMENT_ACK) assert(strcmp(reply, "*#*1##") == 0);
        if (scenario == FRAGMENT_NACK) assert(strcmp(reply, "*#*0##") == 0);
        if (scenario == REPLY_FULL) assert(strlen(reply) == sizeof(reply) - 1 && reads == 1);
        return 0;
    }
    struct c300x_config config = {0};
    config.video_rtp_port_start = 5000;
    config.video_av_high_resolution = 1;
    assert(c300x_device_media_start(&config));
    c300x_device_media_stop(&config);
    assert(command_count == 4 && opened == 4 && closed == 4);
    assert(strcmp(commands[0], "*7*300#127#0#0#1#5002#0*##") == 0);
    assert(strcmp(commands[1], "*7*300#127#0#0#1#5000#2*##") == 0);
    assert(strcmp(commands[2], "*7*301#127#0#0#1#5000#2*##") == 0);
    assert(strcmp(commands[3], "*7*301#127#0#0#1#5002#0*##") == 0);
    assert(elapsed == 4 * 300 + 300);
    /* C300X 3.0.x and C100X: the low stream (#1) is the one bt_av_media sends on. */
    command_count = 0;
    config.video_av_high_resolution = 0;
    assert(c300x_device_media_start(&config));
    c300x_device_media_stop(&config);
    assert(strcmp(commands[0], "*7*300#127#0#0#1#5002#1*##") == 0);
    assert(strcmp(commands[3], "*7*301#127#0#0#1#5002#1*##") == 0);
    return 0;
}
