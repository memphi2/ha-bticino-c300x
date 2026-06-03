#include "activations.h"

#include <stdio.h>
#include <string.h>

int c300x_activation_is_executable(const struct c300x_activation *activation)
{
    if (activation->press_command[0] != '\0') {
        return 1;
    }
    if (activation->address[0] == '\0') {
        return 0;
    }
    return strcmp(activation->type, "lock") == 0
        || strcmp(activation->type, "light") == 0
        || strcmp(activation->type, "stair_light") == 0;
}

void c300x_activation_press_release_commands(
    const struct c300x_activation *activation,
    char *press,
    size_t press_len,
    char *release,
    size_t release_len
)
{
    press[0] = '\0';
    release[0] = '\0';
    if (activation->press_command[0] != '\0') {
        snprintf(press, press_len, "%s", activation->press_command);
        if (activation->release_command[0] != '\0') {
            snprintf(release, release_len, "%s", activation->release_command);
        }
        return;
    }
    if (activation->address[0] == '\0') {
        return;
    }
    if (strcmp(activation->type, "lock") == 0) {
        snprintf(press, press_len, "*8*19*%s##", activation->address);
        snprintf(release, release_len, "*8*20*%s##", activation->address);
    } else if (strcmp(activation->type, "light") == 0 || strcmp(activation->type, "stair_light") == 0) {
        snprintf(press, press_len, "*8*21*%s##", activation->address);
    }
}
