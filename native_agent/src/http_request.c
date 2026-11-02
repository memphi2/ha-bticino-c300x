#include "http_request.h"
#include "system_metrics.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <unistd.h>

static void request_path_and_query(
    const char *line_path,
    char *path,
    size_t path_len,
    char *query,
    size_t query_len
)
{
    char copied_path[256];
    const char *normalized_path = line_path ? line_path : "";
    const char *query_start;
    snprintf(copied_path, sizeof(copied_path), "%s", normalized_path);
    query_start = strchr(copied_path, '?');
    if (path_len > 0) {
        path[0] = '\0';
    }
    if (query_len > 0) {
        query[0] = '\0';
    }
    if (query_start == NULL) {
        size_t path_size = strlen(copied_path);
        if (path_size >= path_len) {
            path_size = path_len > 0 ? path_len - 1 : 0;
        }
        if (path_len > 0) {
            memcpy(path, copied_path, path_size);
            path[path_size] = '\0';
        }
        return;
    }
    if (query_start > copied_path) {
        size_t path_size = (size_t)(query_start - copied_path);
        if (path_size >= path_len) {
            path_size = path_len > 0 ? path_len - 1 : 0;
        }
        if (path_len > 0) {
            memcpy(path, copied_path, path_size);
            path[path_size] = '\0';
        }
    } else if (path_len > 0) {
        path[0] = '/';
        path[1] = '\0';
    }
    if (query_len > 0) {
        snprintf(query, query_len, "%s", query_start + 1);
    }
}

int parse_request(char *buffer, struct request *request)
{
    char *line_end;
    char *header_end;
    char *headers_start;
    char *line_path;

    memset(request, 0, sizeof(*request));
    line_end = strstr(buffer, "\r\n");
    if (line_end == NULL) {
        return 0;
    }
    *line_end = '\0';
    line_path = request->path;
    if (sscanf(buffer, "%7s %255s", request->method, line_path) != 2) {
        return 0;
    }
    request_path_and_query(line_path, request->path, sizeof(request->path), request->query, sizeof(request->query));
    headers_start = line_end + 2;
    header_end = strstr(headers_start, "\r\n\r\n");
    if (header_end == NULL) {
        return 0;
    }
    *header_end = '\0';
    snprintf(request->headers, sizeof(request->headers), "%s", headers_start);
    snprintf(request->body, sizeof(request->body), "%s", header_end + 4);
    request->body_len = strlen(request->body);
    return 1;
}

static int content_length_from_buffer(const char *buffer, const char *header_end, size_t *length)
{
    const char *line = strstr(buffer, "\r\n");
    int seen = 0;

    *length = 0;
    if (line == NULL || line >= header_end) {
        return 0;
    }
    line += 2;
    while (line < header_end) {
        const char *line_end = strstr(line, "\r\n");
        const char *value;
        char *endptr;
        unsigned long parsed;

        if (line_end == NULL || line_end > header_end) {
            line_end = header_end;
        }
        if ((size_t)(line_end - line) >= strlen("transfer-encoding:")
            && strncasecmp(line, "transfer-encoding:", strlen("transfer-encoding:")) == 0) {
            return 0;
        }
        if (
            (size_t)(line_end - line) >= strlen("content-length:")
            && strncasecmp(line, "content-length:", strlen("content-length:")) == 0
        ) {
            value = line + strlen("content-length:");
            while (value < line_end && (*value == ' ' || *value == '\t')) {
                value++;
            }
            if (seen || value == line_end || !isdigit((unsigned char)*value)) {
                return 0;
            }
            errno = 0;
            parsed = strtoul(value, &endptr, 10);
            if (errno != 0 || endptr == value) {
                return 0;
            }
            while (endptr < line_end && (*endptr == ' ' || *endptr == '\t')) {
                endptr++;
            }
            if (endptr != line_end) {
                return 0;
            }
            *length = parsed > REQUEST_BUFFER_SIZE ? REQUEST_BUFFER_SIZE : (size_t)parsed;
            seen = 1;
        }
        if (line_end >= header_end) {
            break;
        }
        line = line_end + 2;
    }
    return 1;
}

int c300x_http_request_status(char *buffer, size_t used, size_t capacity, int *size_error)
{
    *size_error = 0;
    if (used >= capacity) {
        *size_error = 1;
        return -1;
    }
    if (memchr(buffer, '\0', used) != NULL) {
        *size_error = -1;
        return -1;
    }
    buffer[used] = '\0';
    char *header_end = strstr(buffer, "\r\n\r\n");
    if (header_end != NULL) {
        size_t header_len = (size_t)(header_end + 4 - buffer);
        size_t content_len;
        if (!content_length_from_buffer(buffer, header_end, &content_len)) {
            *size_error = -1;
            return -1;
        }
        if (content_len > capacity - header_len - 1) {
            *size_error = 1;
            return -1;
        }
        if (used > header_len + content_len) {
            *size_error = -1;
            return -1;
        }
        if (used == header_len + content_len) {
            return 1;
        }
    }
    if (used + 1 == capacity) {
        *size_error = 1;
        return -1;
    }
    return 0;
}

int receive_http_request(int client_fd, char *buffer, size_t buffer_len, int *too_large)
{
    size_t used = 0;
    long long deadline = c300x_system_metrics_monotonic_ms() + C300X_HTTP_REQUEST_TIMEOUT_MS;

    *too_large = 0;
    while (used + 1 < buffer_len) {
        long long remaining = deadline - c300x_system_metrics_monotonic_ms();
        struct pollfd ready = {.fd = client_fd, .events = POLLIN};
        ssize_t received;

        if (remaining <= 0) {
            return 0;
        }
        int result = poll(&ready, 1, (int)remaining);
        if (result < 0 && errno == EINTR) {
            continue;
        }
        if (result <= 0) {
            return 0;
        }
        received = recv(client_fd, buffer + used, buffer_len - used - 1, MSG_DONTWAIT);
        if (received < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) {
            continue;
        }
        if (received <= 0) {
            return 0;
        }
        used += (size_t)received;
        int status = c300x_http_request_status(buffer, used, buffer_len, too_large);
        if (status != 0) {
            return status > 0;
        }
    }
    *too_large = 1;
    return 0;
}
