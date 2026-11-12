#include "http_response.h"
#include "http_util.h"
#include <stdio.h>
#include <string.h>

void send_response(
    int client_fd,
    int status,
    const char *reason,
    const char *body,
    const char *extra_headers
)
{
    char header[1024];
    size_t body_len = strlen(body);
    int header_len = snprintf(
        header,
        sizeof(header),
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %zu\r\n"
        "Connection: close\r\n"
        "%s"
        "\r\n",
        status,
        reason,
        body_len,
        extra_headers != NULL ? extra_headers : ""
    );

    if (header_len <= 0 || (size_t)header_len >= sizeof(header)
        || !send_all_bytes(client_fd, header, (size_t)header_len)) {
        return;
    }
    (void)send_all_bytes(client_fd, body, body_len);
}
