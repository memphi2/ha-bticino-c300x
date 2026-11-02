#include "../src/http.c"
#include <assert.h>

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
    close(pair[0]);
    close(pair[1]);
}

int main(void)
{
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
