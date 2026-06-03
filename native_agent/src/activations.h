#ifndef C300X_ACTIVATIONS_H
#define C300X_ACTIVATIONS_H

#include <stddef.h>

#include "c300x_agent.h"

int c300x_activation_is_executable(const struct c300x_activation *activation);
void c300x_activation_press_release_commands(
    const struct c300x_activation *activation,
    char *press,
    size_t press_len,
    char *release,
    size_t release_len
);

#endif
