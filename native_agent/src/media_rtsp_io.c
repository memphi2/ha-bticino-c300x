#include "media_rtsp_io.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

int parse_client_port(const char *transport)
{
    const char *pos = strstr(transport, "client_port=");
    if (pos == NULL) {
        return 0;
    }
    return atoi(pos + 12);
}

int parse_interleaved_channel(const char *transport)
{
    const char *pos = strstr(transport, "interleaved=");
    if (pos == NULL) {
        return -1;
    }
    return atoi(pos + 12);
}

int c300x_rtsp_connection_add(int fds[RTSP_CONNECTION_LIMIT], int fd)
{
    for (int index = 0; index < RTSP_CONNECTION_LIMIT; index++) {
        if (fds[index] == 0) {
            fds[index] = fd + 1;
            return index;
        }
    }
    return -1;
}

void c300x_rtsp_connections_shutdown(const int fds[RTSP_CONNECTION_LIMIT])
{
    for (int index = 0; index < RTSP_CONNECTION_LIMIT; index++) {
        if (fds[index] > 0) {
            shutdown(fds[index] - 1, SHUT_RDWR);
        }
    }
}

static ssize_t send_all(int fd, const void *buf, size_t len)
{
    const char *p = buf;
    size_t left = len;
    while (left > 0) {
        ssize_t n = send(fd, p, left, MSG_NOSIGNAL);
        if (n <= 0) {
            return n;
        }
        p += n;
        left -= (size_t)n;
    }
    return (ssize_t)len;
}

void send_rtsp_response(
    int fd,
    int status,
    const char *cseq,
    const char *headers,
    const char *body
) {
    const char *status_text = status == 200 ? "OK" : (status == 401 ? "Unauthorized" : "Error");
    size_t body_len = body ? strlen(body) : 0;
    char response[4096];
    int n = snprintf(
        response,
        sizeof(response),
        "RTSP/1.0 %d %s\r\n"
        "CSeq: %s\r\n"
        "%s"
        "Content-Length: %zu\r\n"
        "\r\n"
        "%s",
        status,
        status_text,
        cseq && cseq[0] ? cseq : "1",
        headers ? headers : "",
        body_len,
        body ? body : ""
    );
    if (n > 0 && n < (int)sizeof(response)) {
        (void)send_all(fd, response, (size_t)n);
    }
}
