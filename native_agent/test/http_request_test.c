#include "../src/http_request.h"
#include "../src/system_metrics.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

static void deadline_test(void)
{
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    pid_t child = fork();
    assert(child >= 0);
    if (child == 0) {
        close(pair[0]);
        const char *fragment = "GET / HTTP/1.1\r\nHost: localhost\r\n";
        while (*fragment) {
            if (send(pair[1], fragment++, 1, MSG_NOSIGNAL) != 1) {
                break;
            }
            usleep(75000);
        }
        close(pair[1]);
        _exit(0);
    }
    close(pair[1]);
    char buffer[REQUEST_BUFFER_SIZE];
    int too_large;
    long long started = c300x_system_metrics_monotonic_ms();
    assert(!receive_http_request(pair[0], buffer, sizeof(buffer), &too_large));
    long long elapsed = c300x_system_metrics_monotonic_ms() - started;
    assert(elapsed >= 400 && elapsed < 1500);
    close(pair[0]);
    assert(waitpid(child, NULL, 0) == child);
}

static void framing_test(const char *payload, int expected, int expected_size_error)
{
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(send(pair[1], payload, strlen(payload), MSG_NOSIGNAL) == (ssize_t)strlen(payload));
    assert(shutdown(pair[1], SHUT_WR) == 0);
    char buffer[REQUEST_BUFFER_SIZE];
    int size_error = 0;
    assert(receive_http_request(pair[0], buffer, sizeof(buffer), &size_error) == expected);
    assert(size_error == expected_size_error);
    if (expected) {
        struct request parsed;
        assert(parse_request(buffer, &parsed));
        assert(strcmp(parsed.path, "/") == 0);
    }
    close(pair[0]);
    close(pair[1]);
}

static void target_bounds_test(void)
{
    char buffer[REQUEST_BUFFER_SIZE];
    char target[C300X_HTTP_TARGET_SIZE + 2];
    struct request parsed;
    memset(target, 'a', sizeof(target));
    memcpy(target, "/homeassistant?entities=", strlen("/homeassistant?entities="));
    target[600] = '\0';
    snprintf(buffer, sizeof(buffer), "GET %s HTTP/1.1\r\nHost: test\r\n\r\n", target);
    assert(parse_request(buffer, &parsed));
    assert(strcmp(parsed.query, strchr(target, '?') + 1) == 0);
    memset(target, 'a', sizeof(target));
    memcpy(target, "/?q=", 4);
    target[C300X_HTTP_TARGET_SIZE - 1] = '\0';
    snprintf(buffer, sizeof(buffer), "GET %s HTTP/1.1\r\nHost: test\r\n\r\n", target);
    assert(parse_request(buffer, &parsed));
    target[C300X_HTTP_TARGET_SIZE - 1] = 'a';
    target[C300X_HTTP_TARGET_SIZE] = '\0';
    snprintf(buffer, sizeof(buffer), "GET %s HTTP/1.1\r\nHost: test\r\n\r\n", target);
    assert(!parse_request(buffer, &parsed));
    memset(target, 'a', 256);
    target[0] = '/';
    target[256] = '\0';
    snprintf(buffer, sizeof(buffer), "GET %s HTTP/1.1\r\nHost: test\r\n\r\n", target);
    assert(!parse_request(buffer, &parsed));
}

int main(void)
{
    target_bounds_test();
    deadline_test();
    framing_test("POST / HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}", 1, 0);
    framing_test("POST / HTTP/1.1\r\nContent-Length: 100\r\n\r\n{}", 0, 0);
    framing_test("POST / HTTP/1.1\r\nContent-Length: 2x\r\n\r\n{}", 0, -1);
    framing_test("POST / HTTP/1.1\r\nContent-Length: -2\r\n\r\n{}", 0, -1);
    framing_test("POST / HTTP/1.1\r\nContent-Length:\r\n\r\n", 0, -1);
    framing_test("POST / HTTP/1.1\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}", 0, -1);
    framing_test("POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n", 0, -1);
    framing_test("POST / HTTP/1.1\r\nContent-Length: 9000\r\n\r\n", 0, 1);
    framing_test("POST / HTTP/1.1\r\nContent-Length: 1\r\n\r\n{}", 0, -1);
    framing_test("GET / HTTP/1.1\r\nHost: localhost\r\n\r\n", 1, 0);
    return 0;
}
