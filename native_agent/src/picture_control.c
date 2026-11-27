#include "picture_control.h"
#include "picture_worker.h"
#include "ringer_control.h"
#include "http_util.h"
#include "json_util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const char *picture_name(enum picture_field field)
{
    static const char *const names[] = {"", "read", "brightness", "contrast", "saturation"};
    return field >= PICTURE_READ && field <= PICTURE_SATURATION ? names[field] : "";
}

static void send_values(int fd, const int values[3])
{
    char body[128];
    snprintf(body, sizeof(body), "{\"ok\":true,\"brightness\":%d,\"contrast\":%d,\"saturation\":%d}\n",
             values[0], values[1], values[2]);
    c300x_http_send_json(fd, 200, "OK", body);
}

void picture_request(struct c300x_ringer_control *control, struct c300x_video_control *worker,
    struct c300x_video *video, const struct c300x_config *config, int fd, const struct request *request)
{
    struct picture_command command = {PICTURE_READ, 0};
    if (!strcmp(request->method, "POST")) {
        char name[24];
        command.field = PICTURE_NONE;
        if (c300x_json_object_valid(request->body)
            && c300x_json_string_field_checked(request->body, "control", name, sizeof(name)) == 1) {
            for (int i = PICTURE_BRIGHTNESS; i <= PICTURE_SATURATION; i++)
                if (!strcmp(name, picture_name(i))) command.field = i;
        }
        if (!command.field || c300x_json_int_field_checked(request->body, "value", &command.value) != 1
            || command.value < 0 || command.value > 100 || command.value % 10) {
            c300x_http_send_json(fd, 400, "Bad Request", "{\"error\":\"invalid_picture_control\"}\n");
            return;
        }
    } else if (strcmp(request->method, "GET")) {
        c300x_http_send_json(fd, 405, "Method Not Allowed", "{\"error\":\"method_not_allowed\"}\n");
        return;
    }
    struct c300x_video_status status;
    int values[3];
    c300x_video_status(video, &status);
    switch (picture_worker_request(worker, video, &status, config, &command, values)) {
    case PICTURE_DIRECT: send_values(fd, values); break;
    case PICTURE_LEGACY: c300x_gui_picture_request(control, fd, command); break;
    case PICTURE_DEFERRED: break;
    case PICTURE_BUSY: c300x_http_send_json(fd, 409, "Conflict", "{\"error\":\"media_busy\"}\n"); break;
    case PICTURE_NOT_APPLIED:
        c300x_http_send_json(fd, 409, "Conflict", "{\"error\":\"picture_not_applied\"}\n"); break;
    case PICTURE_UNAVAILABLE:
        c300x_http_send_json(fd, 409, "Conflict", "{\"error\":\"picture_controls_unavailable\"}\n"); break;
    }
}

void picture_reply(int fd, const struct picture_command *command, const char *query)
{
    char text[16];
    int values[3];
    for (int i = PICTURE_BRIGHTNESS; i <= PICTURE_SATURATION; i++) {
        query_param_value(query, picture_name(i), text, sizeof(text));
        if (!*text || strlen(text) > 3 || strspn(text, "0123456789") != strlen(text) || atoi(text) > 100) {
            c300x_http_send_json(fd, 409, "Conflict", "{\"error\":\"picture_controls_unavailable\"}\n");
            return;
        }
        values[i - PICTURE_BRIGHTNESS] = atoi(text);
    }
    if (command->field != PICTURE_READ && values[command->field - PICTURE_BRIGHTNESS] != command->value) {
        c300x_http_send_json(fd, 409, "Conflict", "{\"error\":\"picture_not_applied\"}\n");
        return;
    }
    send_values(fd, values);
}
