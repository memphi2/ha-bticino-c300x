#include "mqtt_output.h"

#include <errno.h>
#include <string.h>
#include <sys/socket.h>

size_t c300x_mqtt_output_pending(const struct c300x_mqtt_output *output)
{
    return output->used - output->offset;
}

int c300x_mqtt_output_enqueue(struct c300x_mqtt_output *output, unsigned char type,
    const unsigned char *payload, size_t size, long long now)
{
    unsigned char header[5] = {type};
    size_t header_size = 1, remaining = size;
    size_t pending = c300x_mqtt_output_pending(output);
    size_t limit = sizeof(output->bytes) - ((type & 0xf0) == 0x30 ? 2 : 0);
    if (size > 3072 || (size > 0 && payload == NULL)) {
        return 0;
    }
    do {
        unsigned char byte = (unsigned char)(remaining % 128);
        remaining /= 128;
        header[header_size++] = byte | (remaining > 0 ? 0x80 : 0);
    } while (remaining > 0);
    if (pending > limit || size + header_size > limit - pending) {
        return 0;
    }
    if (output->offset > 0) {
        memmove(output->bytes, output->bytes + output->offset, pending);
    }
    memcpy(output->bytes + pending, header, header_size);
    if (size > 0) {
        memcpy(output->bytes + pending + header_size, payload, size);
    }
    output->offset = 0;
    output->used = pending + header_size + size;
    if (pending == 0) {
        output->deadline_ms = now + C300X_MQTT_WRITE_TIMEOUT_MS;
    }
    return 1;
}

int c300x_mqtt_output_flush(struct c300x_mqtt_output *output, int fd, long long now)
{
    size_t pending = c300x_mqtt_output_pending(output);
    if (pending == 0) {
        return 0;
    }
    // Native MQTT is local plaintext, as before; never wait on backpressure.
    // codeql[cpp/cleartext-transmission]
    ssize_t sent = send(fd, output->bytes + output->offset, pending,
        MSG_NOSIGNAL | MSG_DONTWAIT);
    if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
        return 0;
    }
    if (sent <= 0) {
        return -1;
    }
    output->offset += (size_t)sent;
    if (output->offset == output->used) {
        output->offset = output->used = 0;
        output->deadline_ms = 0;
    } else {
        output->deadline_ms = now + C300X_MQTT_WRITE_TIMEOUT_MS;
    }
    return (int)sent;
}

int c300x_mqtt_output_timeout(const struct c300x_mqtt_output *output, long long now)
{
    if (c300x_mqtt_output_pending(output) == 0) {
        return -1;
    }
    long long remaining = output->deadline_ms - now;
    return remaining <= 0 ? 0 : (int)remaining;
}
