#include <sys/socket.h>
static ssize_t short_send(int fd, const void *buffer, size_t length, int flags);
#define send short_send
#include "../src/http_util.c"
#undef send
#include "../src/http.c"
#include <assert.h>

static int interrupted;
static ssize_t short_send(int fd, const void *buffer, size_t length, int flags)
{
    if (!interrupted++) {
        errno = EINTR;
        return -1;
    }
    return send(fd, buffer, length > 4 ? 4 : length, flags);
}

int main(void)
{
    char path[] = "/tmp/c300x-http-file-test-XXXXXX";
    const char body[] = "0123456789abcdef0123456789abcdef";
    int file = mkstemp(path);
    assert(file >= 0);
    assert(write(file, body, sizeof(body) - 1) == sizeof(body) - 1);
    close(file);
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    send_file_response(pair[0], path, "application/octet-stream", "no-store");
    close(pair[0]);
    char response[2048];
    ssize_t count = recv(pair[1], response, sizeof(response) - 1, MSG_WAITALL);
    assert(count > 0);
    response[count] = '\0';
    char *payload = strstr(response, "\r\n\r\n");
    assert(payload != NULL && strcmp(payload + 4, body) == 0);
    assert(strstr(response, "Content-Length: 32\r\n") != NULL);
    close(pair[1]);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    close(pair[1]);
    send_file_response(pair[0], path, "application/octet-stream", "no-store");
    close(pair[0]);
    unlink(path);
    return 0;
}
