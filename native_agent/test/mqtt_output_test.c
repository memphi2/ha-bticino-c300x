#include "../src/mqtt_output.h"

#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <sys/socket.h>

static unsigned char wire[20000];
static size_t wire_size, allowance;
static int send_error, calls;

ssize_t __wrap_send(int fd, const void *buffer, size_t size, int flags)
{
    assert(fd == 123 && (flags & MSG_DONTWAIT) && (flags & MSG_NOSIGNAL));
    calls++;
    if (send_error) {
        errno = send_error;
        return -1;
    }
    size_t sent = size < allowance ? size : allowance;
    assert(wire_size + sent <= sizeof(wire));
    memcpy(wire + wire_size, buffer, sent);
    wire_size += sent;
    return (ssize_t)sent;
}

int main(void)
{
    struct c300x_mqtt_output output = {0};
    unsigned char payload[3072];
    memset(payload, 'x', sizeof(payload));
    assert(c300x_mqtt_output_timeout(&output, 0) == -1);
    assert(!c300x_mqtt_output_enqueue(&output, 0x30, payload, SIZE_MAX, 0));
    assert(!c300x_mqtt_output_enqueue(&output, 0x30, NULL, 1, 0));
    assert(c300x_mqtt_output_enqueue(&output, 0x30, payload, sizeof(payload), 10));
    assert(output.used == 3075 && output.deadline_ms == 510);
    struct c300x_mqtt_output saved = output;
    assert(!c300x_mqtt_output_enqueue(&output, 0x30, payload, 1, 20));
    assert(memcmp(&saved, &output, sizeof(saved)) == 0);
    assert(c300x_mqtt_output_enqueue(&output, 0xc0, NULL, 0, 20));
    assert(output.used == sizeof(output.bytes) && output.deadline_ms == 510);
    for (int i = 0; i < 3; i++) {
        send_error = i == 0 ? EINTR : i == 1 ? EAGAIN : EWOULDBLOCK;
        int before = calls;
        assert(c300x_mqtt_output_flush(&output, 123, 100) == 0 && calls == before + 1);
        assert(output.offset == 0 && output.deadline_ms == 510);
    }
    send_error = 0;
    allowance = 1;
    assert(c300x_mqtt_output_flush(&output, 123, 200) == 1);
    assert(output.deadline_ms == 700);
    allowance = 100;
    assert(c300x_mqtt_output_flush(&output, 123, 300) == 100);
    assert(c300x_mqtt_output_enqueue(&output, 0x30, payload, 3, 350));
    assert(output.offset == 0 && output.deadline_ms == 800);
    allowance = sizeof(wire);
    int sent = c300x_mqtt_output_flush(&output, 123, 400);
    assert(sent > 0 && output.used == 0 && output.offset == 0);
    assert(c300x_mqtt_output_timeout(&output, 99999) == -1);
    assert(wire_size == 3082);
    assert(wire[0] == 0x30 && wire[1] == 0x80 && wire[2] == 0x18);
    assert(memcmp(wire + 3, payload, sizeof(payload)) == 0);
    assert(wire[3075] == 0xc0 && wire[3076] == 0);
    assert(wire[3077] == 0x30 && wire[3078] == 3);
    assert(memcmp(wire + 3079, payload, 3) == 0);
    assert(c300x_mqtt_output_enqueue(&output, 0x82, payload, 1, 1000));
    assert(c300x_mqtt_output_timeout(&output, 1499) == 1);
    assert(c300x_mqtt_output_timeout(&output, 1500) == 0);
    send_error = EPIPE;
    assert(c300x_mqtt_output_flush(&output, 123, 1200) == -1);
    assert(c300x_mqtt_output_pending(&output) == 3);
    send_error = 0;
    allowance = 0;
    assert(c300x_mqtt_output_flush(&output, 123, 1300) == -1);
    return 0;
}
