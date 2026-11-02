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

int main(void)
{
    deadline_test();
    return 0;
}
