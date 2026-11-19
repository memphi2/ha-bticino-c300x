/* Blocking request reader for tests. The agent reads requests without
 * blocking, per client slot; tests that play a peer want one whole request. */
#ifndef C300X_TEST_HTTP_REQUEST_READER_H
#define C300X_TEST_HTTP_REQUEST_READER_H

#include <errno.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/types.h>

#include "../src/http_request.h"
#include "../src/system_metrics.h"

static int receive_http_request(int client_fd, char *buffer, size_t buffer_len, int *too_large)
{
    size_t used = 0;
    long long deadline = c300x_system_metrics_monotonic_ms() + C300X_HTTP_REQUEST_TIMEOUT_MS;

    *too_large = 0;
    while (used + 1 < buffer_len) {
        long long remaining = deadline - c300x_system_metrics_monotonic_ms();
        struct pollfd ready = {.fd = client_fd, .events = POLLIN};
        ssize_t received;

        if (remaining <= 0) {
            return 0;
        }
        int result = poll(&ready, 1, (int)remaining);
        if (result < 0 && errno == EINTR) {
            continue;
        }
        if (result <= 0) {
            return 0;
        }
        received = recv(client_fd, buffer + used, buffer_len - used - 1, MSG_DONTWAIT);
        if (received < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) {
            continue;
        }
        if (received <= 0) {
            return 0;
        }
        used += (size_t)received;
        int status = c300x_http_request_status(buffer, used, buffer_len, too_large);
        if (status != 0) {
            return status > 0;
        }
    }
    *too_large = 1;
    return 0;
}

#endif
