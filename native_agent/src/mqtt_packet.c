#include "mqtt_packet.h"

#include <string.h>

size_t c300x_mqtt_write_utf8(unsigned char *out, size_t out_len, const char *value)
{
    size_t len = strlen(value);
    if (len > 65535 || out_len < len + 2) {
        return 0;
    }
    out[0] = (unsigned char)((len >> 8) & 0xff);
    out[1] = (unsigned char)(len & 0xff);
    memcpy(out + 2, value, len);
    return len + 2;
}

size_t c300x_mqtt_connect_payload(const struct c300x_config *config, unsigned char *payload, size_t payload_len)
{
    size_t used = 0;
    unsigned char flags = 0x02;
    unsigned char keepalive_hi;
    unsigned char keepalive_lo;

    if (config->mqtt_username[0] != '\0') {
        flags |= 0x80;
    }
    if (config->mqtt_password[0] != '\0') {
        flags |= 0x40;
    }
    if (config->mqtt_availability_topic[0] != '\0') {
        flags |= 0x04;
        flags |= 0x20;
    }
    {
        size_t written = c300x_mqtt_write_utf8(payload + used, payload_len - used, "MQTT");
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (used + 4 >= payload_len) {
        return 0;
    }
    payload[used++] = 4;
    payload[used++] = flags;
    keepalive_hi = (unsigned char)(((unsigned int)config->mqtt_keepalive_seconds >> 8) & 0xff);
    keepalive_lo = (unsigned char)((unsigned int)config->mqtt_keepalive_seconds & 0xff);
    payload[used++] = keepalive_hi;
    payload[used++] = keepalive_lo;
    {
        size_t written = c300x_mqtt_write_utf8(payload + used, payload_len - used, config->mqtt_client_id);
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (config->mqtt_availability_topic[0] != '\0') {
        size_t written = c300x_mqtt_write_utf8(payload + used, payload_len - used, config->mqtt_availability_topic);
        if (written == 0) {
            return 0;
        }
        used += written;
        written = c300x_mqtt_write_utf8(payload + used, payload_len - used, "offline");
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (config->mqtt_username[0] != '\0') {
        size_t written = c300x_mqtt_write_utf8(payload + used, payload_len - used, config->mqtt_username);
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (config->mqtt_password[0] != '\0') {
        size_t written = c300x_mqtt_write_utf8(payload + used, payload_len - used, config->mqtt_password);
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (used == 0 || used >= payload_len) {
        return 0;
    }
    return used;
}

size_t c300x_mqtt_subscribe_payload(const struct c300x_config *config, unsigned char *payload, size_t payload_len)
{
    size_t used = 0;
    payload[used++] = 0;
    payload[used++] = 1;
    {
        size_t written = c300x_mqtt_write_utf8(payload + used, payload_len - used, config->mqtt_command_topic);
        if (written == 0) {
            return 0;
        }
        used += written;
    }
    if (used + 1 >= payload_len) {
        return 0;
    }
    payload[used++] = (unsigned char)config->mqtt_qos;
    return used;
}

int c300x_mqtt_json_raw_field(const char *data_json, char *out, size_t out_len)
{
    const char *key = strstr(data_json, "\"raw\"");
    const char *ptr;
    size_t used = 0;
    if (key == NULL || out_len == 0) {
        return 0;
    }
    ptr = strchr(key, ':');
    if (ptr == NULL) {
        return 0;
    }
    ptr++;
    while (*ptr == ' ' || *ptr == '\t') {
        ptr++;
    }
    if (*ptr != '"') {
        return 0;
    }
    ptr++;
    while (*ptr != '\0' && *ptr != '"') {
        char ch = *ptr++;
        if (ch == '\\' && *ptr != '\0') {
            ch = *ptr++;
        }
        if (used + 1 >= out_len) {
            return 0;
        }
        out[used++] = ch;
    }
    if (*ptr != '"') {
        return 0;
    }
    out[used] = '\0';
    return used > 0;
}
