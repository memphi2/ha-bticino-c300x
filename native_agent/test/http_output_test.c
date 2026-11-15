#include <sys/socket.h>
static ssize_t limited_send(int fd, const void *data, size_t size, int flags);
#define send limited_send
#include "../src/http_util.c"
#include "../src/video_snapshot.h"
#undef send
#include <assert.h>
#include <fcntl.h>

static int blocked;
static int interrupt_next;
static int short_writes;
static ssize_t limited_send(int fd, const void *data, size_t size, int flags)
{
    assert(flags & MSG_DONTWAIT);
    if (interrupt_next) {
        interrupt_next = 0;
        errno = EINTR;
        return -1;
    }
    if (blocked) {
        errno = EAGAIN;
        return -1;
    }
    return send(fd, data, short_writes && size > 7 ? 7 : size, flags);
}

static int output_count(void)
{
    int count = 0;
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS; i++) {
        if (outputs[i].data != NULL) {
            count++;
            assert(outputs[i].size <= C300X_HTTP_OUTPUT_LIMIT);
        }
    }
    return count;
}

static void test_large_response(void)
{
    int pair[2];
    const size_t size = 100000;
    char *body = malloc(size);
    char *received = malloc(size);
    struct pollfd fds[C300X_HTTP_MAX_OUTPUTS];
    assert(body && received);
    memset(body, 'm', size);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    blocked = 1;
    assert(c300x_http_write(pair[0], body, size));
    close_agent_socket(pair[0]);
    blocked = 0;
    short_writes = 0;
    size_t used = 0;
    while (used < size) {
        c300x_http_outputs_prepare(fds);
        assert(poll(fds, C300X_HTTP_MAX_OUTPUTS, 10) >= 0);
        c300x_http_outputs_handle(fds);
        ssize_t n = recv(pair[1], received + used, size - used, MSG_DONTWAIT);
        if (n > 0) used += (size_t)n;
        else assert(n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK));
    }
    assert(memcmp(body, received, size) == 0);
    assert(output_count() == 0);
    close(pair[1]);
    free(body);
    free(received);
}

static void test_progress_extends_the_deadline_up_to_a_total(void)
{
    int pair[2];
    const size_t size = 100000;
    char *body = calloc(size, 1);
    struct pollfd fds[C300X_HTTP_MAX_OUTPUTS];
    struct http_output *slot = NULL;
    assert(body);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    blocked = 1;
    assert(c300x_http_write(pair[0], body, size));
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS; i++) {
        if (outputs[i].data != NULL) slot = &outputs[i];
    }
    assert(slot != NULL);
    /* A slow link still sends: the two seconds count from the last progress. */
    slot->deadline = output_now() + 50;
    blocked = 0;
    short_writes = 1;
    c300x_http_outputs_prepare(fds);
    assert(poll(fds, C300X_HTTP_MAX_OUTPUTS, 10) >= 0);
    c300x_http_outputs_handle(fds);
    assert(slot->sent == 7);
    assert(slot->deadline > output_now() + C300X_HTTP_OUTPUT_TIMEOUT_MS / 2);
    /* A peer that reads a little now and then cannot hold the slot for ever. */
    slot->limit = output_now() + 20;
    c300x_http_outputs_prepare(fds);
    assert(poll(fds, C300X_HTTP_MAX_OUTPUTS, 10) >= 0);
    c300x_http_outputs_handle(fds);
    assert(slot->deadline <= output_now() + 20);
    short_writes = 0;
    clear_output(slot, 1);
    close_agent_socket(pair[0]);
    close(pair[1]);
    free(body);
}

static void test_largest_snapshot_is_accepted(void)
{
    int pair[2];
    const size_t size = 54U + C300X_SNAPSHOT_MAX_WIDTH * 3U * C300X_SNAPSHOT_MAX_HEIGHT;
    char *body = calloc(size, 1);
    assert(body);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    blocked = 1;
    assert(c300x_http_write(pair[0], "HTTP/1.1 200 OK\r\n\r\n", 19));
    assert(c300x_http_write(pair[0], body, size));
    assert(output_count() == 1);
    close_agent_socket(pair[0]);
    close(pair[1]);
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS; i++) {
        if (outputs[i].data != NULL) clear_output(&outputs[i], 1);
    }
    free(body);
    blocked = 0;
}

static void test_queue_memory_budget(void)
{
    int first[2], second[2];
    const size_t size = C300X_HTTP_OUTPUT_QUEUE_LIMIT / 5 * 3;
    char *body = calloc(size, 1);
    assert(body);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, first) == 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, second) == 0);
    blocked = 1;
    assert(c300x_http_write(first[0], body, size));
    assert(!c300x_http_write(second[0], body, size));
    assert(output_count() == 1);
    /* Growing an existing response is subject to the same total limit. */
    assert(!c300x_http_write(first[0], body, size));
    assert(output_count() == 0);
    close_agent_socket(first[0]);
    close_agent_socket(second[0]);
    close(first[1]);
    close(second[1]);
    free(body);
    blocked = 0;
}

int main(void)
{
    int pair[2];
    struct pollfd fds[C300X_HTTP_MAX_OUTPUTS];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    int small = 4096;
    assert(setsockopt(pair[0], SOL_SOCKET, SO_SNDBUF, &small, sizeof(small)) == 0);
    char body[32761], response[65536];
    memset(body, 'x', sizeof(body) - 1);
    body[sizeof(body) - 1] = '\0';
    interrupt_next = 1;
    short_writes = 1;
    long long started = output_now();
    c300x_http_send_json(pair[0], 200, "OK", body);
    close_agent_socket(pair[0]);
    assert(output_now() - started < 100);
    assert(output_count() == 1);
    size_t used = 0;
    for (int i = 0; output_count() && i < 10000; i++) {
        c300x_http_outputs_prepare(fds);
        assert(poll(fds, C300X_HTTP_MAX_OUTPUTS, 10) >= 0);
        c300x_http_outputs_handle(fds);
        ssize_t n = recv(pair[1], response + used, sizeof(response) - used - 1, MSG_DONTWAIT);
        if (n > 0) { used += (size_t)n; }
    }
    assert(output_count() == 0);
    ssize_t n;
    while ((n = recv(pair[1], response + used, sizeof(response) - used - 1, 0)) > 0) {
        used += (size_t)n;
    }
    response[used] = '\0';
    char *payload = strstr(response, "\r\n\r\n");
    assert(payload != NULL && strcmp(payload + 4, body) == 0);
    assert(strstr(response, "Content-Length: 32760\r\n"));
    assert(fcntl(pair[0], F_GETFD) == -1 && errno == EBADF);
    close(pair[1]);

    /* A non-reading peer must not block either normal or rejected requests. */
    blocked = 1;
    int peers[C300X_HTTP_MAX_OUTPUTS];
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS + 40; i++) {
        assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
        c300x_http_send_json(pair[0], 400, "Bad Request", "{}\n");
        close_agent_socket(pair[0]);
        if (i < C300X_HTTP_MAX_OUTPUTS) {
            peers[i] = pair[1];
        } else {
            assert(recv(pair[1], response, sizeof(response), 0) == 0);
            close(pair[1]);
        }
        assert(output_count() <= C300X_HTTP_MAX_OUTPUTS);
    }
    assert(output_count() == C300X_HTTP_MAX_OUTPUTS);
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS; i++) {
        outputs[i].deadline = output_now() - 1;
    }
    assert(c300x_http_outputs_prepare(fds) == 0);
    c300x_http_outputs_handle(fds);
    assert(output_count() == 0);
    for (int i = 0; i < C300X_HTTP_MAX_OUTPUTS; i++) {
        assert(recv(peers[i], response, sizeof(response), 0) == 0);
        close(peers[i]);
    }
    assert(c300x_http_outputs_prepare(fds) == -1);

    {
        /* The UDP event port takes frames only from this host itself. */
        struct sockaddr_in source = {.sin_family = AF_INET};
        source.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        assert(c300x_udp_source_is_local(&source));
        source.sin_addr.s_addr = htonl(0xC0000201U);
        assert(!c300x_udp_source_is_local(&source));
        struct ifaddrs *own = NULL;
        assert(getifaddrs(&own) == 0);
        for (struct ifaddrs *item = own; item != NULL; item = item->ifa_next) {
            if (item->ifa_addr != NULL && item->ifa_addr->sa_family == AF_INET) {
                assert(c300x_udp_source_is_local((const struct sockaddr_in *)item->ifa_addr));
            }
        }
        freeifaddrs(own);
        assert(!c300x_udp_source_is_local(NULL));
    }

    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    c300x_http_send_json(pair[0], 200, "OK", "{}");
    close_agent_socket(pair[0]);
    c300x_http_outputs_close();
    assert(output_count() == 0);
    assert(recv(pair[1], response, sizeof(response), 0) == 0);
    close(pair[1]);
    test_large_response();
    test_queue_memory_budget();
    test_largest_snapshot_is_accepted();
    test_progress_extends_the_deadline_up_to_a_total();
    return 0;
}
