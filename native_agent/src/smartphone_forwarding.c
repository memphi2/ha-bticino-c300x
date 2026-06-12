#include "smartphone_forwarding.h"

#include <stdio.h>

const char *c300x_smartphone_mode_from_code(int code)
{
    if (code == 0) {
        return "enabled";
    }
    if (code == 1) {
        return "in-house-only";
    }
    if (code == 2) {
        return "blocked";
    }
    return NULL;
}

int c300x_smartphone_code_from_reply(const char *reply, int *code)
{
    int parsed = -1;

    if (reply == NULL || code == NULL) {
        return 0;
    }
    if (
        sscanf(reply, "*#8**37*%d##", &parsed) != 1
        && sscanf(reply, "*#8**#37*%d##", &parsed) != 1
    ) {
        return 0;
    }
    if (c300x_smartphone_mode_from_code(parsed) == NULL) {
        return 0;
    }
    *code = parsed;
    return 1;
}
