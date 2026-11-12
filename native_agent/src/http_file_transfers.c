#include "http_file_transfers.h"
#include "http_util.h"
#include "system_metrics.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

static void clear_transfer(struct c300x_http_file_transfer *transfer)
{
    close_agent_socket(transfer->fd);
    if (transfer->file != NULL) {
        fclose(transfer->file);
    }
    free(transfer->buffer);
    memset(transfer, 0, sizeof(*transfer));
    transfer->fd = -1;
}

void c300x_http_file_transfers_init(struct c300x_http_file_transfers *transfers)
{
    memset(transfers, 0, sizeof(*transfers));
    for (int i = 0; i < C300X_HTTP_MAX_FILE_TRANSFERS; i++) {
        transfers->slots[i].fd = -1;
    }
}

int c300x_http_file_transfers_start(struct c300x_http_file_transfers *transfers,
    int fd, const char *path, const char *content_type)
{
    struct c300x_http_file_transfer *transfer = NULL;
    for (int i = 0; i < C300X_HTTP_MAX_FILE_TRANSFERS; i++) {
        if (transfers->slots[i].fd < 0) {
            transfer = &transfers->slots[i];
            break;
        }
    }
    if (transfer == NULL) {
        c300x_http_send_json(fd, 503, "Service Unavailable",
            "{\"ok\":false,\"error\":\"media_transfers_busy\"}\n");
        return 0;
    }
    transfer->file = fopen(path, "rb");
    if (transfer->file == NULL || fseek(transfer->file, 0, SEEK_END) != 0
        || (transfer->remaining = ftell(transfer->file)) < 0
        || fseek(transfer->file, 0, SEEK_SET) != 0) {
        clear_transfer(transfer);
        c300x_http_send_json(fd, 404, "Not Found",
            "{\"ok\":false,\"error\":\"media_not_found\"}\n");
        return 0;
    }
    set_fd_cloexec(fileno(transfer->file));
    transfer->buffer = malloc(C300X_HTTP_FILE_BUFFER_SIZE);
    if (transfer->buffer == NULL) {
        clear_transfer(transfer);
        c300x_http_send_json(fd, 503, "Service Unavailable",
            "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        return 0;
    }
    int length = snprintf(transfer->buffer, C300X_HTTP_FILE_BUFFER_SIZE,
        "HTTP/1.1 200 OK\r\nContent-Type: %s\r\nContent-Length: %ld\r\n"
        "Cache-Control: no-store\r\nConnection: close\r\n\r\n",
        content_type != NULL ? content_type : "application/octet-stream", transfer->remaining);
    if (length < 0 || length >= C300X_HTTP_FILE_BUFFER_SIZE) {
        clear_transfer(transfer);
        c300x_http_send_json(fd, 500, "Internal Server Error",
            "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        return 0;
    }
    transfer->used = (size_t)length;
    transfer->fd = fd;
    transfer->deadline = c300x_system_metrics_monotonic_ms() + C300X_HTTP_FILE_IDLE_TIMEOUT_MS;
    return 1;
}

int c300x_http_file_transfers_owns(const struct c300x_http_file_transfers *transfers, int fd)
{
    for (int i = 0; i < C300X_HTTP_MAX_FILE_TRANSFERS; i++) {
        if (fd >= 0 && transfers->slots[i].fd == fd) {
            return 1;
        }
    }
    return 0;
}

int c300x_http_file_transfers_prepare(struct c300x_http_file_transfers *transfers,
    struct pollfd *fds, long long now)
{
    int timeout = -1;
    for (int i = 0; i < C300X_HTTP_MAX_FILE_TRANSFERS; i++) {
        struct c300x_http_file_transfer *transfer = &transfers->slots[i];
        fds[i] = (struct pollfd){.fd = transfer->fd, .events = POLLOUT};
        if (transfer->fd < 0) {
            continue;
        }
        long long remaining = transfer->deadline - now;
        int wait = remaining > 0 ? (int)remaining : 0;
        if (timeout < 0 || wait < timeout) {
            timeout = wait;
        }
    }
    return timeout;
}

void c300x_http_file_transfers_handle(struct c300x_http_file_transfers *transfers,
    const struct pollfd *fds, long long now)
{
    for (int i = 0; i < C300X_HTTP_MAX_FILE_TRANSFERS; i++) {
        struct c300x_http_file_transfer *transfer = &transfers->slots[i];
        if (transfer->fd < 0) {
            continue;
        }
        if (transfer->deadline <= now) {
            clear_transfer(transfer);
            continue;
        }
        if (fds[i].fd != transfer->fd) {
            continue;
        }
        if (fds[i].revents & (POLLERR | POLLHUP | POLLNVAL)) {
            clear_transfer(transfer);
            continue;
        }
        if (!(fds[i].revents & POLLOUT)) {
            continue;
        }
        /* A ready download must not monopolize call events or other clients. */
        for (int writes = 0; transfer->fd >= 0 && writes < 2; writes++) {
            if (transfer->sent == transfer->used) {
                if (transfer->remaining == 0) {
                    clear_transfer(transfer);
                    break;
                }
                size_t take = transfer->remaining < C300X_HTTP_FILE_BUFFER_SIZE
                    ? (size_t)transfer->remaining : C300X_HTTP_FILE_BUFFER_SIZE;
                transfer->used = fread(transfer->buffer, 1, take, transfer->file);
                transfer->sent = 0;
                if (transfer->used == 0) {
                    clear_transfer(transfer);
                    break;
                }
                transfer->remaining -= (long)transfer->used;
            }
            ssize_t sent = send(transfer->fd, transfer->buffer + transfer->sent,
                transfer->used - transfer->sent, MSG_NOSIGNAL | MSG_DONTWAIT);
            if (sent < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) {
                break;
            }
            if (sent <= 0) {
                clear_transfer(transfer);
                break;
            }
            transfer->sent += (size_t)sent;
            transfer->deadline = now + C300X_HTTP_FILE_IDLE_TIMEOUT_MS;
            if (transfer->sent == transfer->used && transfer->remaining == 0) {
                clear_transfer(transfer);
            }
        }
    }
}

void c300x_http_file_transfers_close(struct c300x_http_file_transfers *transfers)
{
    for (int i = 0; i < C300X_HTTP_MAX_FILE_TRANSFERS; i++) {
        clear_transfer(&transfers->slots[i]);
    }
}
