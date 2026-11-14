#include <assert.h>
#include "../src/mqtt_bridge.c"

static void publish(struct c300x_mqtt *mqtt, const char *command)
{
    const char *topic = "Bticino/rx";
    size_t n = strlen(command), t = strlen(topic);
    unsigned char *p = mqtt->rx_buffer + mqtt->rx_len;
    *p++ = 0x30; *p++ = (unsigned char)(2 + t + n);
    *p++ = 0; *p++ = (unsigned char)t;
    memcpy(p, topic, t); p += t;
    memcpy(p, command, n);
    mqtt->rx_len += 4 + t + n;
}

int main(void)
{
    struct c300x_mqtt mqtt;
    c300x_mqtt_init(&mqtt);
    publish(&mqtt, "*8*19*20##");
    publish(&mqtt, "*8*20*20##");
    mqtt_process_rx(&mqtt);
    char command[128];
    assert(c300x_mqtt_take_command(&mqtt, command, sizeof(command)));
    assert(strcmp(command, "*8*19*20##") == 0);
    assert(c300x_mqtt_take_command(&mqtt, command, sizeof(command)));
    assert(strcmp(command, "*8*20*20##") == 0);
    assert(!c300x_mqtt_take_command(&mqtt, command, sizeof(command)));
    assert(mqtt.rx_len == 0);
    publish(&mqtt, "*8*19*20##");
    size_t full = mqtt.rx_len;
    mqtt.rx_len--;
    assert(!c300x_mqtt_take_command(&mqtt, command, sizeof(command)));
    mqtt.rx_len = full;
    assert(c300x_mqtt_take_command(&mqtt, command, sizeof(command)));
    assert(strcmp(command, "*8*19*20##") == 0);
    return 0;
}
