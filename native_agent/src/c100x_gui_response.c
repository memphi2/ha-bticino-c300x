#include "c100x_gui_response.h"
#include "json_util.h"
#include <stdio.h>
#include <string.h>

static int valid_body(const char *body)
{
    static const char *keys[] = {"ok", "probe", "generation", "gui_ready", "idle", "present", "installation_verified"};
    unsigned int seen = 0;
    const char *end = body + strlen(body), *cursor = body + strspn(body, " \r\n\t");
    if (!c300x_json_object_valid(body)) return 0;
    cursor++;
    for (;;) {
        char key[32];
        cursor += strspn(cursor, " \r\n\t");
        if (*cursor == '}') return 1;
        if (!c300x_json_decode_string(cursor, end, key, sizeof(key), &cursor)) return 0;
        unsigned int bit = 0;
        for (unsigned int i = 0; i < sizeof(keys) / sizeof(*keys); i++)
            if (!strcmp(key, keys[i])) bit = 1u << i;
        if (!bit || (seen & bit)) return 0;
        seen |= bit;
        cursor += strspn(cursor, " \r\n\t");
        if (*cursor++ != ':') return 0;
        cursor = c300x_json_skip_value(cursor, end);
        if (!cursor) return 0;
        cursor += strspn(cursor, " \r\n\t");
        if (*cursor == '}') return 1;
        if (*cursor++ != ',') return 0;
    }
}

int c100x_gui_readiness_validate(const char *body, const char *generation, const char *probe)
{
    char actual_generation[65], actual_probe[33];
    int ok = 0, ready = 0;
    return strlen(generation) == 64 && strspn(generation, "0123456789abcdef") == 64
        && strlen(probe) == 32 && strspn(probe, "0123456789abcdef") == 32 && valid_body(body)
        && c300x_json_bool_field(body, "ok", &ok) && ok
        && c300x_json_bool_field(body, "gui_ready", &ready) && ready
        && c300x_json_string_field_checked(body, "generation", actual_generation, sizeof(actual_generation)) == 1
        && c300x_json_string_field_checked(body, "probe", actual_probe, sizeof(actual_probe)) == 1
        && !strcmp(generation, actual_generation) && !strcmp(probe, actual_probe);
}

int c100x_gui_response_cli(const char *mode, const char *generation, const char *probe)
{
    char body[513], challenge[33];
    int ok = 0, idle = 0;
    size_t size = fread(body, 1, sizeof(body) - 1, stdin);
    body[size] = '\0';
    if (ferror(stdin) || size == sizeof(body) - 1 || strlen(body) != size
        || !valid_body(body)) return 1;
    if (!strcmp(mode, "challenge")) {
        if (!c300x_json_bool_field(body, "ok", &ok) || !ok
            || c300x_json_string_field_checked(body, "probe", challenge, sizeof(challenge)) != 1
            || strlen(challenge) != 32 || strspn(challenge, "0123456789abcdef") != 32) return 1;
        puts(challenge);
        return 0;
    }
    if (strcmp(mode, "ready") && strcmp(mode, "idle")) return 2;
    if (!c100x_gui_readiness_validate(body, generation, probe)) return 1;
    if (!strcmp(mode, "idle") && (!c300x_json_bool_field(body, "idle", &idle) || !idle)) return 1;
    return 0;
}
