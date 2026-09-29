#include "smartphone_forwarding.h"

#include <stdio.h>
#include <string.h>

const char *c300x_smartphone_mode_from_code(int code)
{
    if (code == 0) {
        return "enabled";
    }
    if (code == 1) {
        return "homeassistant";
    }
    if (code == 2) {
        return "blocked";
    }
    if (code == 3) {
        return "unprovisioned";
    }
    return NULL;
}

int c300x_smartphone_code_from_reply(const char *reply, int *code)
{
    int parsed = -1;
    int end = 0;

    if (reply == NULL || code == NULL) {
        return 0;
    }
    (void)sscanf(reply, "*#8**37*%d##%n", &parsed, &end);
    if (end == 0) {
        (void)sscanf(reply, "*#8**#37*%d##%n", &parsed, &end);
    }
    if (end == 0 || reply[end] != '\0') {
        return 0;
    }
    if (c300x_smartphone_mode_from_code(parsed) == NULL) {
        return 0;
    }
    *code = parsed;
    return 1;
}

const char *c300x_smartphone_mode_from_reply(const char *reply)
{
    int code;

    if (c300x_smartphone_code_from_reply(reply, &code)) {
        return c300x_smartphone_mode_from_code(code);
    }
    return NULL;
}

const char *c300x_smartphone_command_from_mode(const char *mode)
{
    if (mode == NULL) {
        return NULL;
    }
    if (strcmp(mode, "enabled") == 0) {
        return "*#8**#37*0##";
    }
    if (strcmp(mode, "homeassistant") == 0) {
        return "*#8**#37*1##";
    }
    if (strcmp(mode, "blocked") == 0) {
        return "*#8**#37*2##";
    }
    return NULL;
}
