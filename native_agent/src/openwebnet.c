#include "c300x_agent.h"
#include "openwebnet_call.h"
#include "string_util.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define OPENWEBNET_ACK "*#*1##"
#define OPENWEBNET_HANDSHAKE "*99*0##"
#define OPENWEBNET_DRAIN_TIMEOUT_MS 250
#define OPENWEBNET_MAX_READBACK_FRAMES 4

static void set_error(char *error, size_t error_len, const char *message)
{
    if (error_len > 0) {
        c300x_copy_string(error, error_len, message);
    }
}

static void set_socket_timeout(int fd, int timeout_ms)
{
    struct timeval timeout;
    timeout.tv_sec = timeout_ms / 1000;
    timeout.tv_usec = (timeout_ms % 1000) * 1000;
    (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
}

static int connect_openwebnet(const struct c300x_openwebnet_call *config, char *error, size_t error_len)
{
    int fd;
    struct sockaddr_in address;

    /* The loop may start a child while a worker holds this socket. */
    fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) {
        set_error(error, error_len, "openwebnet_socket_failed");
        return -1;
    }
    set_socket_timeout(fd, config->timeout_ms);
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons(config->port);
    if (inet_pton(AF_INET, config->host, &address.sin_addr) != 1) {
        set_error(error, error_len, "openwebnet_invalid_host");
        close(fd);
        return -1;
    }
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        set_error(error, error_len, "openwebnet_connect_failed");
        close(fd);
        return -1;
    }
    return fd;
}

static int write_all(int fd, const char *text)
{
    size_t len = strlen(text);
    size_t sent = 0;

    while (sent < len) {
        ssize_t written = send(fd, text + sent, len - sent, MSG_NOSIGNAL);
        if (written <= 0) {
            return 0;
        }
        sent += (size_t)written;
    }
    return 1;
}

static int read_frame(int fd, char *frame, size_t frame_len)
{
    size_t used = 0;

    if (frame_len == 0) {
        return 0;
    }
    frame[0] = '\0';
    while (used + 1 < frame_len) {
        char ch;
        ssize_t received = recv(fd, &ch, 1, 0);
        if (received <= 0) {
            return 0;
        }
        frame[used++] = ch;
        frame[used] = '\0';
        if (used >= 2 && frame[used - 2] == '#' && frame[used - 1] == '#') {
            return 1;
        }
    }
    return 0;
}

static int wait_readable(int fd, int timeout_ms)
{
    int result;

    do {
        fd_set readfds;
        struct timeval timeout;

        FD_ZERO(&readfds);
        FD_SET(fd, &readfds);
        timeout.tv_sec = timeout_ms / 1000;
        timeout.tv_usec = (timeout_ms % 1000) * 1000;
        result = select(fd + 1, &readfds, NULL, NULL, &timeout);
    } while (result < 0 && errno == EINTR);

    return result > 0;
}

static void drain_openwebnet_frames(int fd)
{
    char frame[C300X_MAX_FRAME_LEN];

    while (wait_readable(fd, OPENWEBNET_DRAIN_TIMEOUT_MS)) {
        if (!read_frame(fd, frame, sizeof(frame))) {
            return;
        }
    }
}

static int read_non_ack_frame(
    int fd,
    const char *stage,
    char *reply,
    size_t reply_len,
    char *error,
    size_t error_len
)
{
    char frame[C300X_MAX_FRAME_LEN];
    int index;

    for (index = 0; index < OPENWEBNET_MAX_READBACK_FRAMES; index++) {
        if (!read_frame(fd, frame, sizeof(frame))) {
            snprintf(error, error_len, "%s_timeout", stage);
            return 0;
        }
        if (strcmp(frame, OPENWEBNET_ACK) == 0) {
            continue;
        }
        snprintf(reply, reply_len, "%s", frame);
        return 1;
    }
    snprintf(error, error_len, "%s_ack_only", stage);
    return 0;
}

static int expect_ack(int fd, const char *stage, char *error, size_t error_len)
{
    char frame[C300X_MAX_FRAME_LEN];

    if (!read_frame(fd, frame, sizeof(frame))) {
        snprintf(error, error_len, "%s_timeout", stage);
        return 0;
    }
    if (strcmp(frame, OPENWEBNET_ACK) != 0) {
        snprintf(error, error_len, "%s_unexpected_frame", stage);
        return 0;
    }
    return 1;
}

static void sleep_ms(int delay_ms)
{
    struct timespec requested;
    struct timespec remaining;

    requested.tv_sec = delay_ms / 1000;
    requested.tv_nsec = (long)(delay_ms % 1000) * 1000000L;
    while (nanosleep(&requested, &remaining) != 0 && errno == EINTR) {
        requested = remaining;
    }
}

static int handshake(int fd, char *error, size_t error_len)
{
    if (!expect_ack(fd, "openwebnet_greeting", error, error_len)) {
        return 0;
    }
    if (!write_all(fd, OPENWEBNET_HANDSHAKE)) {
        set_error(error, error_len, "openwebnet_handshake_write_failed");
        return 0;
    }
    return expect_ack(fd, "openwebnet_handshake", error, error_len);
}

static int send_now(
    const struct c300x_openwebnet_call *config,
    const char *command,
    char *reply,
    size_t reply_len,
    char *error,
    size_t error_len
)
{
    int fd = connect_openwebnet(config, error, error_len);
    char frame[C300X_MAX_FRAME_LEN];

    if (fd < 0) {
        return 0;
    }
    if (!handshake(fd, error, error_len)) {
        close(fd);
        return 0;
    }
    if (!write_all(fd, command)) {
        set_error(error, error_len, "openwebnet_command_write_failed");
        close(fd);
        return 0;
    }
    if (!read_frame(fd, frame, sizeof(frame))) {
        set_error(error, error_len, "openwebnet_command_timeout");
        close(fd);
        return 0;
    }
    snprintf(reply, reply_len, "%s", frame);
    close(fd);
    return 1;
}

static int sequence_now(
    const struct c300x_openwebnet_call *config,
    const char *first_command,
    int delay_ms,
    const char *second_command,
    char *error,
    size_t error_len
)
{
    int fd = connect_openwebnet(config, error, error_len);

    if (fd < 0) {
        return 0;
    }
    if (!handshake(fd, error, error_len)) {
        close(fd);
        return 0;
    }
    if (!write_all(fd, first_command) || !expect_ack(fd, "openwebnet_first_command", error, error_len)) {
        close(fd);
        return 0;
    }
    if (delay_ms > 0) {
        sleep_ms(delay_ms);
    }
    if (!write_all(fd, second_command) || !expect_ack(fd, "openwebnet_second_command", error, error_len)) {
        close(fd);
        return 0;
    }
    close(fd);
    return 1;
}

static int write_readback_now(
    const struct c300x_openwebnet_call *config,
    const char *write_command,
    int delay_ms,
    const char *readback_command,
    char *write_reply,
    size_t write_reply_len,
    char *readback_reply,
    size_t readback_reply_len,
    char *error,
    size_t error_len
)
{
    int fd = connect_openwebnet(config, error, error_len);
    char frame[C300X_MAX_FRAME_LEN];

    if (fd < 0) {
        return 0;
    }
    if (!handshake(fd, error, error_len)) {
        close(fd);
        return 0;
    }
    if (!write_all(fd, write_command)) {
        set_error(error, error_len, "openwebnet_write_command_failed");
        close(fd);
        return 0;
    }
    if (!read_frame(fd, frame, sizeof(frame))) {
        set_error(error, error_len, "openwebnet_write_response_timeout");
        close(fd);
        return 0;
    }
    snprintf(write_reply, write_reply_len, "%s", frame);
    drain_openwebnet_frames(fd);
    if (delay_ms > 0) {
        sleep_ms(delay_ms);
    }
    if (!write_all(fd, readback_command)) {
        set_error(error, error_len, "openwebnet_readback_write_failed");
        close(fd);
        return 0;
    }
    if (!read_non_ack_frame(
            fd,
            "openwebnet_readback_response",
            readback_reply,
            readback_reply_len,
            error,
            error_len
        )) {
        close(fd);
        return 0;
    }
    drain_openwebnet_frames(fd);
    close(fd);
    return 1;
}

int c300x_openwebnet_call_same(const struct c300x_openwebnet_call *left, const struct c300x_openwebnet_call *right)
{
    return left->kind == right->kind && left->port == right->port
        && left->timeout_ms == right->timeout_ms && left->delay_ms == right->delay_ms
        && strcmp(left->host, right->host) == 0 && strcmp(left->first, right->first) == 0
        && strcmp(left->second, right->second) == 0;
}

void c300x_openwebnet_call_copy_result(struct c300x_openwebnet_call *call, const struct c300x_openwebnet_call *result)
{
    call->ok = result->ok;
    memcpy(call->reply, result->reply, sizeof(call->reply));
    memcpy(call->readback, result->readback, sizeof(call->readback));
    memcpy(call->error, result->error, sizeof(call->error));
}

int c300x_openwebnet_call_fail(struct c300x_openwebnet_call *call, const char *error)
{
    call->ok = 0;
    snprintf(call->error, sizeof(call->error), "%s", error);
    return 1;
}

c300x_openwebnet_hook_fn c300x_openwebnet_hook;
void (*c300x_openwebnet_before_inline)(void);
int c300x_openwebnet_call_deferred;

int c300x_openwebnet_deferred(void)
{
    return c300x_openwebnet_call_deferred;
}

void c300x_openwebnet_execute(struct c300x_openwebnet_call *call)
{
    call->reply[0] = '\0';
    call->readback[0] = '\0';
    call->error[0] = '\0';
    if (call->kind == C300X_OPENWEBNET_SEQUENCE) {
        call->ok = sequence_now(call, call->first, call->delay_ms, call->second,
            call->error, sizeof(call->error));
    } else if (call->kind == C300X_OPENWEBNET_WRITE_READBACK) {
        call->ok = write_readback_now(call, call->first, call->delay_ms, call->second,
            call->reply, sizeof(call->reply), call->readback, sizeof(call->readback),
            call->error, sizeof(call->error));
    } else {
        call->ok = send_now(call, call->first, call->reply, sizeof(call->reply),
            call->error, sizeof(call->error));
    }
}

/* Run the call now, or hand it to the hook that keeps the caller's loop free.
 * Zero with an empty error and c300x_openwebnet_deferred() set means the
 * caller has to return at once and will be called again with the result. */
static int run_call(const struct c300x_config *config, struct c300x_openwebnet_call *call,
    int kind, const char *first, int delay_ms, const char *second, char *error, size_t error_len)
{
    memset(call, 0, sizeof(*call));
    call->kind = kind;
    call->delay_ms = delay_ms;
    call->port = config->openwebnet_port;
    call->timeout_ms = config->openwebnet_timeout_ms;
    c300x_copy_string(call->host, sizeof(call->host), config->openwebnet_host);
    if (strlen(first) >= sizeof(call->first) || (second != NULL && strlen(second) >= sizeof(call->second))) {
        set_error(error, error_len, "openwebnet_command_too_long");
        return 0;
    }
    c300x_copy_string(call->first, sizeof(call->first), first);
    c300x_copy_string(call->second, sizeof(call->second), second != NULL ? second : "");
    if (c300x_openwebnet_hook == NULL || !c300x_openwebnet_hook(call)) {
        /* One session with the bus at a time: let a worker's exchange end first. */
        if (c300x_openwebnet_before_inline != NULL) {
            c300x_openwebnet_before_inline();
        }
        c300x_openwebnet_execute(call);
    }
    set_error(error, error_len, call->error);
    return call->ok;
}

int c300x_openwebnet_send(const struct c300x_config *config, const char *command,
    char *reply, size_t reply_len, char *error, size_t error_len)
{
    struct c300x_openwebnet_call call;
    if (!run_call(config, &call, C300X_OPENWEBNET_SEND, command, 0, NULL, error, error_len)) {
        return 0;
    }
    snprintf(reply, reply_len, "%s", call.reply);
    return 1;
}

int c300x_openwebnet_sequence(const struct c300x_config *config, const char *first_command,
    int delay_ms, const char *second_command, char *error, size_t error_len)
{
    struct c300x_openwebnet_call call;
    return run_call(config, &call, C300X_OPENWEBNET_SEQUENCE, first_command, delay_ms,
        second_command, error, error_len);
}

int c300x_openwebnet_write_readback(const struct c300x_config *config, const char *write_command,
    int delay_ms, const char *readback_command, char *write_reply, size_t write_reply_len,
    char *readback_reply, size_t readback_reply_len, char *error, size_t error_len)
{
    struct c300x_openwebnet_call call;
    if (!run_call(config, &call, C300X_OPENWEBNET_WRITE_READBACK, write_command, delay_ms,
            readback_command, error, error_len)) {
        /* The write reply is reported even when the readback failed, as before. */
        if (call.reply[0] != '\0') {
            snprintf(write_reply, write_reply_len, "%s", call.reply);
        }
        return 0;
    }
    snprintf(write_reply, write_reply_len, "%s", call.reply);
    snprintf(readback_reply, readback_reply_len, "%s", call.readback);
    return 1;
}
