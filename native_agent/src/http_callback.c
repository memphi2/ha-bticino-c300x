#include "http_callback.h"
#include "http_util.h"
#include "system_metrics.h"

#include <ctype.h>
#include <errno.h>
#include <netdb.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int c300x_http_post_callback(const char *url, const char *token, const char *event_json, int timeout_ms)
{
    char host[256];
    char host_header[288];
    char port[16];
    char path[256];
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    struct addrinfo *item;
    int fd = -1;
    char header[1024];
    char response[64];
    int ok = 0;

    if (strncmp(url, "http://", 7) != 0 || !parse_http_url(url, host, sizeof(host), port, sizeof(port), path, sizeof(path))) {
        return 0;
    }
    memset(&hints, 0, sizeof(hints));
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_family = AF_UNSPEC;
    if (getaddrinfo(host, port, &hints, &result) != 0) {
        return 0;
    }
    http_host_header_value(host, port, host_header, sizeof(host_header));
    for (item = result; item != NULL; item = item->ai_next) {
        fd = socket(item->ai_family, item->ai_socktype, item->ai_protocol);
        if (fd < 0) {
            continue;
        }
        set_fd_cloexec(fd);
        set_socket_timeout(fd, timeout_ms);
        if (connect(fd, item->ai_addr, item->ai_addrlen) == 0) {
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(result);
    if (fd < 0) {
        return 0;
    }
    snprintf(
        header,
        sizeof(header),
        "POST %s HTTP/1.1\r\n"
        "Host: %s\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %zu\r\n"
        "%s%s%s"
        "Connection: close\r\n"
        "\r\n",
        path,
        host_header,
        strlen(event_json),
        token[0] != '\0' ? C300X_EVENT_TOKEN_HEADER ": " : "",
        token[0] != '\0' ? token : "",
        token[0] != '\0' ? "\r\n" : ""
    );
    if (send_all_bytes(fd, header, strlen(header))
        && send_all_bytes(fd, event_json, strlen(event_json))) {
        size_t used = 0;
        long long deadline = c300x_system_metrics_monotonic_ms() + timeout_ms;
        while (used + 1 < sizeof(response)) {
            long long remaining = deadline - c300x_system_metrics_monotonic_ms();
            if (remaining <= 0) {
                break;
            }
            set_socket_timeout(fd, (int)remaining);
            ssize_t received = recv(fd, response + used, sizeof(response) - used - 1, 0);
            if (received < 0 && errno == EINTR) {
                continue;
            }
            if (received <= 0) {
                break;
            }
            used += (size_t)received;
            response[used] = '\0';
            if (strchr(response, '\n') != NULL) {
                ok = (strncmp(response, "HTTP/1.1 2", 10) == 0 || strncmp(response, "HTTP/1.0 2", 10) == 0)
                    && strchr(response, '\n') - response >= 13 && isdigit((unsigned char)response[10])
                    && isdigit((unsigned char)response[11]) && response[12] == ' ';
                break;
            }
        }
    }
    close(fd);
    return ok;
}
