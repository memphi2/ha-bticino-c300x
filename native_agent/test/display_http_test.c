/* Exercise the production display callback with a socketpair, not a live HA. */
#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

static int client_fd;
static int interrupt_next_read;
static int read_error;
static size_t response_capacity = 512;
static int callback_socket(int domain, int type, int protocol)
{
    (void)domain;
    (void)type;
    (void)protocol;
    return client_fd;
}

static int callback_connect(int fd, const struct sockaddr *address, socklen_t length)
{
    (void)fd;
    (void)address;
    (void)length;
    return 0;
}

static ssize_t fragmented_recv(int fd, void *buffer, size_t length, int flags)
{
    if (interrupt_next_read) {
        interrupt_next_read = 0;
        errno = EINTR;
        return -1;
    }
    ssize_t received = recv(fd, buffer, length > 3 ? 3 : length, flags);
    if (received == 0 && read_error) {
        errno = read_error;
        return -1;
    }
    return received;
}

#define socket callback_socket
#define connect callback_connect
#define recv fragmented_recv
#include "../src/display_callback.c"
#undef recv
#undef connect
#undef socket

int c300x_https_post(
    const char *url, const char *token_header, const char *token, const char *body,
    char *response, size_t response_len, int timeout_ms,
    long *http_status, const char **error
)
{
    (void)url; (void)token_header; (void)token; (void)body;
    (void)response; (void)response_len; (void)timeout_ms;
    (void)http_status; (void)error;
    abort();
}

static void check_response(const char *wire, int success, const char *body)
{
    int pair[2];
    char response[512];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    client_fd = pair[0];
    assert(send_all_bytes(pair[1], wire, strlen(wire)));
    assert(shutdown(pair[1], SHUT_WR) == 0);
    interrupt_next_read = 1;
    assert(response_capacity <= sizeof(response));
    int ok = c300x_display_post("http://127.0.0.1/callback", "test-secret", 100,
        "{}", response, response_capacity);
    if (ok != success) {
        fprintf(stderr, "Unexpected result %d for response: %s\n", ok, wire);
    }
    assert(ok == success);
    if (success) {
        assert(strcmp(response, body) == 0);
    }
    close(pair[1]);
}

int main(void)
{
    check_response("HTTP/1.1 401 Unauthorized\r\n\r\n{}", 0, NULL);
    check_response("HTTP/1.0 500 Error\r\n\r\n{}", 0, NULL);
    check_response("HTTP/1.1 302 Found\r\n\r\n", 0, NULL);
    check_response("", 0, NULL);
    check_response("HTTP/1.1 2\r\n\r\n", 0, NULL);
    check_response("HTTP/1.1 20x OK\r\n\r\n", 0, NULL);
    check_response("HTTP/1.1 2000 OK\r\n\r\n", 0, NULL);
    check_response("HTTP/1.1 200 OK\r\n", 0, NULL);
    check_response("HTTP/1.1 200 OK", 0, NULL);
    check_response("HTTP/2.0 200 OK\r\n\r\n", 0, NULL);
    check_response("HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n{\"ok\":true}", 1, "{\"ok\":true}");
    check_response("HTTP/1.0 201 Created\r\n\r\n{}", 1, "{}");
    check_response("HTTP/1.1 204 No Content\r\n\r\n", 1, "{}\n");
    read_error = EAGAIN;
    check_response("HTTP/1.1 200 OK\r\n\r\n{}", 0, NULL);
    read_error = ECONNRESET;
    check_response("", 0, NULL);
    read_error = 0;
    for (size_t length = 0; length <= 25; length++) {
        response_capacity = length;
        check_response("HTTP/1.1 200 OK\r\n\r\n{\"ok\":true}", 0, NULL);
    }
    return 0;
}
