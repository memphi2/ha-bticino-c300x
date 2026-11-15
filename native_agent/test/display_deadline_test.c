/* Real display worker, completion handling and HTTP I/O; loopback only. */
#include <assert.h>
#include <pthread.h>
#include "../src/http.c"
#include "../src/time_util.h"

static int listener;

static void *webhook_server(void *unused)
{
    (void)unused;
    for (int request = 0; request < 2; request++) {
        int fd = accept(listener, NULL, NULL);
        assert(fd >= 0);
        struct timeval timeout = {2, 0};
        assert(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
        char input[2048] = {0};
        size_t used = 0;
        while (strstr(input, "\r\n\r\n{}") == NULL) {
            ssize_t count = recv(fd, input + used, sizeof(input) - used - 1, 0);
            assert(count > 0);
            used += (size_t)count;
            input[used] = '\0';
        }
        const char *header = "HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n";
        assert(send_all_bytes(fd, header, strlen(header)));
        if (request == 0) {
            /* Every byte arrives well inside the 100ms idle timeout. */
            for (int i = 0; i < 40; i++) {
                if (send(fd, " ", 1, MSG_NOSIGNAL) != 1) break;
                usleep(20000);
            }
        } else {
            assert(send_all_bytes(fd, "{\"ok\":true}", 11));
        }
        close(fd);
    }
    return NULL;
}

static void expect_status(int fd, const char *status)
{
    char response[1024];
    ssize_t count = recv(fd, response, sizeof(response) - 1, 0);
    assert(count > 0);
    response[count] = '\0';
    assert(strstr(response, status));
    close(fd);
}

static void complete_callback(struct agent_runtime *runtime)
{
    struct pollfd pending = {.fd = c300x_callback_queue_fd(runtime->display_callbacks), .events = POLLIN};
    assert(poll(&pending, 1, 600) == 1);
    finish_display_callback(runtime);
    assert(runtime->display_client_fd == -1);
}

int main(void)
{
    listener = socket(AF_INET, SOCK_STREAM, 0);
    assert(listener >= 0);
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    assert(bind(listener, (struct sockaddr *)&address, sizeof(address)) == 0);
    assert(listen(listener, 2) == 0);
    socklen_t size = sizeof(address);
    assert(getsockname(listener, (struct sockaddr *)&address, &size) == 0);
    pthread_t server;
    assert(pthread_create(&server, NULL, webhook_server, NULL) == 0);
    struct c300x_config config = {.home_assistant_request_timeout_ms = 100};
    struct agent_runtime *runtime = calloc(1, sizeof(*runtime));
    assert(runtime);
    runtime->config = &config;
    runtime->network_online = 1;
    runtime->network_checked_at = time(NULL);
    runtime->display_client_fd = -1;
    runtime->display_bridge_registered = 1;
    strcpy(runtime->display_bridge_shared_secret, "test-secret");
    snprintf(runtime->display_bridge_webhook_url, sizeof(runtime->display_bridge_webhook_url),
        "http://127.0.0.1:%u/callback", ntohs(address.sin_port));
    int first[2], rejected[2], next[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, first) == 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, rejected) == 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, next) == 0);
    long long start = c300x_monotonic_ms();
    forward_to_homeassistant(first[0], &config, runtime, "{}");
    assert(runtime->display_client_fd == first[0]);
    forward_to_homeassistant(rejected[0], &config, runtime, "{}");
    assert(runtime->display_client_fd == first[0]);
    close_agent_socket(rejected[0]);
    expect_status(rejected[1], "display_command_pending");
    complete_callback(runtime);
    long long elapsed = c300x_monotonic_ms() - start;
    assert(elapsed >= 90 && elapsed < 500);
    expect_status(first[1], "502 Bad Gateway");
    forward_to_homeassistant(next[0], &config, runtime, "{}");
    assert(runtime->display_client_fd == next[0]);
    complete_callback(runtime);
    expect_status(next[1], "200 OK");
    assert(pthread_join(server, NULL) == 0);
    close(listener);
    c300x_callback_queue_close(runtime->display_callbacks);
    free(runtime);
    /* Let the detached worker finish destroying its queue before leak checks. */
    usleep(50000);
    return 0;
}
