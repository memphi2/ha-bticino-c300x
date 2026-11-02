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

void send_file_response(
    int client_fd,
    const char *path,
    const char *content_type,
    const char *cache_control
)
{
    FILE *file;
    char header[1024];
    unsigned char buffer[8192];
    int header_len;
    long file_size;

    file = fopen(path, "rb");
    if (file == NULL) {
        c300x_http_send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"media_not_found\"}\n");
        return;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        c300x_http_send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"media_not_found\"}\n");
        return;
    }
    file_size = ftell(file);
    if (file_size < 0 || fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        c300x_http_send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"media_not_found\"}\n");
        return;
    }
    header_len = snprintf(
        header,
        sizeof(header),
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %lld\r\n"
        "Cache-Control: %s\r\n"
        "Connection: close\r\n"
        "\r\n",
        content_type != NULL ? content_type : "application/octet-stream",
        (long long)file_size,
        cache_control != NULL ? cache_control : "no-store"
    );
    if (header_len <= 0 || (size_t)header_len >= sizeof(header)
        || !send_all_bytes(client_fd, header, (size_t)header_len)) {
        fclose(file);
        return;
    }
    for (;;) {
        size_t read_len = fread(buffer, 1, sizeof(buffer), file);
        if (read_len > 0 && !send_all_bytes(client_fd, (const char *)buffer, read_len)) {
            break;
        }
        if (read_len < sizeof(buffer)) {
            break;
        }
    }
    fclose(file);
}
