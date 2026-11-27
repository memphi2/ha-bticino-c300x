#include "picture_control.h"
#include "device_detect.h"
#include "firmware_version.h"
#include "http_util.h"
#include "json_util.h"
#include "openwebnet_call.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PICTURE_ACK "*#*1##"
#define PICTURE_STATUS_PREFIX "*#7**20*"

static const char *const names[] = {"", "read", "brightness", "contrast", "saturation"};

int picture_controls_supported(void)
{
    char firmware[C300X_MAX_VERSION_LEN];
    /* Neither the configured model nor a configured display version proves
     * the station; the installer writes C300X on every one. */
    resolve_device_firmware(NULL, firmware, sizeof(firmware));
    if (c300x_device_model() == C300X_DEVICE_MODEL_C100X) return !strcmp(firmware, "1.5.8");
    return !strcmp(firmware, "1.7.19") || !strcmp(firmware, "2.0.2") || !strcmp(firmware, "3.0.6");
}

int picture_write_frame(enum picture_field field, int value, char *out, size_t out_len)
{
    if (field < PICTURE_BRIGHTNESS || field > PICTURE_SATURATION || value < 0 || value > 100) return 0;
    /* One value only: further ones would replace the station's range. */
    int written = snprintf(out, out_len, "*#7**#%d*%d##", 5 + (field - PICTURE_BRIGHTNESS), value);
    return written > 0 && (size_t)written < out_len;
}

int picture_status_values(const char *frame, int values[3])
{
    int parsed[5];
    const char *cursor = frame;
    if (!frame || strncmp(cursor, PICTURE_STATUS_PREFIX, strlen(PICTURE_STATUS_PREFIX))) return 0;
    cursor += strlen(PICTURE_STATUS_PREFIX) - 1;
    for (int i = 0; i < 5; i++) {
        size_t digits = strspn(cursor + 1, "0123456789");
        if (*cursor != '*' || digits < 1 || digits > 3) return 0;
        parsed[i] = atoi(cursor + 1);
        if (parsed[i] > 100) return 0;
        cursor += 1 + digits;
    }
    if (strcmp(cursor, "##")) return 0;
    memcpy(values, parsed, 3 * sizeof(int));
    return 1;
}

static void send_values(int fd, const int values[3])
{
    char body[128];
    snprintf(body, sizeof(body), "{\"ok\":true,\"brightness\":%d,\"contrast\":%d,\"saturation\":%d}\n",
             values[0], values[1], values[2]);
    c300x_http_send_json(fd, 200, "OK", body);
}

static void refuse(int fd, const char *error)
{
    char body[96];
    snprintf(body, sizeof(body), "{\"error\":\"%s\"}\n", error);
    c300x_http_send_json(fd, 409, "Conflict", body);
}

/* Runs again for the same request until the OpenWebNet worker has answered
 * every exchange; nothing before the last one has another effect. */
void picture_request(const struct c300x_config *config, int fd, const struct request *request)
{
    enum picture_field field = PICTURE_READ;
    int value = 0;
    if (!strcmp(request->method, "POST")) {
        char name[24];
        field = PICTURE_NONE;
        if (c300x_json_object_valid(request->body)
            && c300x_json_string_field_checked(request->body, "control", name, sizeof(name)) == 1) {
            for (int i = PICTURE_BRIGHTNESS; i <= PICTURE_SATURATION; i++)
                if (!strcmp(name, names[i])) field = i;
        }
        if (!field || c300x_json_int_field_checked(request->body, "value", &value) != 1
            || value < 0 || value > 100 || value % 10) {
            c300x_http_send_json(fd, 400, "Bad Request", "{\"error\":\"invalid_picture_control\"}\n");
            return;
        }
    } else if (strcmp(request->method, "GET")) {
        c300x_http_send_json(fd, 405, "Method Not Allowed", "{\"error\":\"method_not_allowed\"}\n");
        return;
    }
    if (!picture_controls_supported()) {
        refuse(fd, "picture_controls_unavailable");
        return;
    }
    char reply[C300X_MAX_FRAME_LEN], readback[C300X_MAX_FRAME_LEN], command[32];
    char error[C300X_MAX_ERROR_LEN];
    int values[3];
    /* The station answers only while a video runs; nothing is written before. */
    if (!c300x_openwebnet_send(config, PICTURE_STATUS_REQUEST, reply, sizeof(reply), error, sizeof(error))
        || !picture_status_values(reply, values)) {
        if (!c300x_openwebnet_deferred()) refuse(fd, "picture_controls_unavailable");
        return;
    }
    if (field == PICTURE_READ) {
        send_values(fd, values);
        return;
    }
    (void)picture_write_frame(field, value, command, sizeof(command));
    if (!c300x_openwebnet_write_readback(config, command, 0, PICTURE_STATUS_REQUEST, reply, sizeof(reply),
                                         readback, sizeof(readback), error, sizeof(error))) {
        if (!c300x_openwebnet_deferred()) refuse(fd, "picture_not_applied");
        return;
    }
    /* The write is acknowledged, or answered with the new value first. */
    if ((strcmp(reply, PICTURE_ACK) && strncmp(reply, "*#7**", 5)) || !picture_status_values(readback, values)
        || values[field - PICTURE_BRIGHTNESS] != value) {
        refuse(fd, "picture_not_applied");
        return;
    }
    send_values(fd, values);
}
