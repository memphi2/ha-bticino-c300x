#include <sys/socket.h>
static ssize_t short_send(int fd, const void *buffer, size_t length, int flags);
#define send short_send
#include "../src/http_util.c"
#include "../src/http_file_transfers.c"
#undef send
#include <assert.h>
#include <fcntl.h>
#include <limits.h>

static int interrupted;
static ssize_t short_send(int fd, const void *buffer, size_t length, int flags)
{
    if (!interrupted++) {
        errno = EINTR;
        return -1;
    }
    if (interrupted == 2) {
        errno = EAGAIN;
        return -1;
    }
    return send(fd, buffer, length > 4 ? 4 : length, flags);
}

int main(void)
{
    struct c300x_http_file_transfers transfers;
    struct pollfd fds[C300X_HTTP_MAX_FILE_TRANSFERS];
    c300x_http_file_transfers_init(&transfers);
    assert(c300x_http_file_transfers_prepare(&transfers, fds, 0) == -1);
    char path[PATH_MAX];
    const char *temporary = getenv("TMPDIR");
    int path_length = snprintf(path, sizeof(path), "%s/c300x-http-file-test-XXXXXX",
                               temporary != NULL ? temporary : "/tmp");
    assert(path_length > 0 && (size_t)path_length < sizeof(path));
    const char body[] = "0123456789abcdef0123456789abcdef";
    int file = mkstemp(path);
    assert(file >= 0);
    assert(write(file, body, sizeof(body) - 1) == sizeof(body) - 1);
    close(file);
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(c300x_http_file_transfers_start(&transfers, pair[0], path, "application/octet-stream"));
    assert(fcntl(fileno(transfers.slots[0].file), F_GETFD) & FD_CLOEXEC);
    for (int iteration = 0; c300x_http_file_transfers_owns(&transfers, pair[0]); iteration++) {
        assert(iteration < 200);
        long long now = c300x_system_metrics_monotonic_ms();
        assert(c300x_http_file_transfers_prepare(&transfers, fds, now) >= 0);
        assert(poll(fds, C300X_HTTP_MAX_FILE_TRANSFERS, 100) > 0);
        c300x_http_file_transfers_handle(&transfers, fds, now);
    }
    char response[2048];
    ssize_t count = recv(pair[1], response, sizeof(response) - 1, MSG_WAITALL);
    assert(count > 0);
    response[count] = '\0';
    char *payload = strstr(response, "\r\n\r\n");
    assert(payload != NULL && strcmp(payload + 4, body) == 0);
    assert(strstr(response, "Content-Length: 32\r\n") != NULL);
    close(pair[1]);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(c300x_http_file_transfers_start(&transfers, pair[0], path, NULL));
    close(pair[1]);
    long long now = c300x_system_metrics_monotonic_ms();
    c300x_http_file_transfers_prepare(&transfers, fds, now);
    assert(poll(fds, C300X_HTTP_MAX_FILE_TRANSFERS, 100) > 0);
    c300x_http_file_transfers_handle(&transfers, fds, now);
    assert(!c300x_http_file_transfers_owns(&transfers, pair[0]));
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(c300x_http_file_transfers_start(&transfers, pair[0], path, NULL));
    now = transfers.slots[0].deadline;
    assert(c300x_http_file_transfers_prepare(&transfers, fds, now) == 0);
    c300x_http_file_transfers_handle(&transfers, fds, now);
    assert(!c300x_http_file_transfers_owns(&transfers, pair[0]));
    close(pair[1]);
    /* A loop iteration that arrives after the idle deadline must not drop a
     * client whose socket is writable: the delay was ours, not the client's. */
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(c300x_http_file_transfers_start(&transfers, pair[0], path, NULL));
    now = transfers.slots[0].deadline + 5000;
    c300x_http_file_transfers_prepare(&transfers, fds, now);
    assert(poll(fds, C300X_HTTP_MAX_FILE_TRANSFERS, 100) > 0);
    c300x_http_file_transfers_handle(&transfers, fds, now);
    assert(c300x_http_file_transfers_owns(&transfers, pair[0]));
    assert(transfers.slots[0].deadline == now + C300X_HTTP_FILE_IDLE_TIMEOUT_MS);
    close(pair[1]);
    c300x_http_file_transfers_close(&transfers);
    assert(c300x_http_file_transfers_prepare(&transfers, fds, now) == -1);
    unlink(path);
    return 0;
}
