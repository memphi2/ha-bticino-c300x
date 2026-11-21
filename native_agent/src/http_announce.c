#include "http_announce.h"
#include "http_util.h"
#include "json_util.h"
#include "media_base64.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ROOT "/api/v1/announcements"

static int refuse(int fd, int status, const char *reason, const char *error)
{
    char body[96];
    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"announcement_%s\"}\n", error);
    c300x_http_send_json(fd, status, reason, body);
    return 1;
}

static int refuse_error(int fd, const char *error)
{
    if (strcmp(error, "busy") == 0) {
        return refuse(fd, 409, "Conflict", error);
    }
    return strncmp(error, "invalid_", 8) == 0 ? refuse(fd, 400, "Bad Request", error)
        : refuse(fd, 500, "Internal Server Error", error);
}

static int reply(const struct c300x_announce *announce, int fd, int duration_ms)
{
    char body[256];
    snprintf(body, sizeof(body),
        "{\"ok\":true,\"supported\":%s,\"playing\":%s,\"result\":\"%s\",\"duration_ms\":%d,\"max_bytes\":%d}\n",
        c300x_announce_supported() ? "true" : "false",
        c300x_announce_playing(announce) && !announce->cleaning ? "true" : "false",
        announce->result, duration_ms, C300X_ANNOUNCE_MAX_BYTES);
    c300x_http_send_json(fd, 200, "OK", body);
    return 1;
}

static int write_piece(struct c300x_announce *announce, int fd, const struct request *request)
{
    struct piece {
        char text[REQUEST_BUFFER_SIZE];
        unsigned char bytes[REQUEST_BUFFER_SIZE];
    } *piece = calloc(1, sizeof(*piece));
    const char *error = "invalid_audio";
    size_t len = 0;
    int offset = -1, ok;

    if (piece == NULL) {
        return refuse(fd, 500, "Internal Server Error", "out_of_memory");
    }
    c300x_json_string_field(request->body, "data", piece->text, sizeof(piece->text));
    ok = c300x_json_int_field(request->body, "offset", &offset)
        && c300x_media_base64_decode(piece->text, piece->bytes, sizeof(piece->bytes), &len)
        && c300x_announce_write(announce, offset, piece->bytes, len, &error);
    free(piece);
    return ok ? reply(announce, fd, 0) : refuse_error(fd, error);
}

int c300x_http_announce_route(struct c300x_announce *announce, int fd, const struct request *request)
{
    const char *action = request->path + sizeof(ROOT) - 1;
    const char *error = "";
    int post = strcmp(request->method, "POST") == 0;
    int volume = 0, duration_ms = 0;

    if (strncmp(request->path, ROOT, sizeof(ROOT) - 1) != 0 || (action[0] != '\0' && action[0] != '/')) {
        return 0;
    }
    if (action[0] == '\0' && strcmp(request->method, "GET") == 0) {
        return reply(announce, fd, 0);
    }
    if (!post) {
        return 0;
    }
    if (!c300x_announce_supported()) {
        return refuse(fd, 409, "Conflict", "unsupported");
    }
    if (strcmp(action, "/audio") == 0) {
        return write_piece(announce, fd, request);
    }
    if (strcmp(action, "/actions/stop") == 0) {
        c300x_announce_stop(announce);
        return reply(announce, fd, 0);
    }
    if (strcmp(action, "/actions/play") != 0) {
        return 0;
    }
    if (!c300x_json_int_field(request->body, "volume", &volume)) {
        return refuse(fd, 400, "Bad Request", "invalid_volume");
    }
    return c300x_announce_play(announce, volume, &duration_ms, &error) ? reply(announce, fd, duration_ms)
        : refuse_error(fd, error);
}
