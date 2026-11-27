#ifndef C300X_ACTIVATIONS_H
#define C300X_ACTIVATIONS_H

#include <stddef.h>

#include "c300x_agent.h"

/* The station's display releases the stair light 100 ms after it pressed
 * it (StaircaseLight: single-shot QTimer of 100 ms, then *8*22), on
 * 1.7.19, 2.0.2, 3.0.6 and the C100X 1.5.8 alike. */
#define C300X_STAIR_LIGHT_RELEASE_MS 100

int c300x_activation_is_executable(const struct c300x_activation *activation);
/* The stair light's press and release frames for where. */
void c300x_stair_light_commands(const char *where, char *press, size_t press_len, char *release,
                                size_t release_len);
/* How long the press is held before the release frame. */
int c300x_activation_hold_ms(const struct c300x_activation *activation, int lock_release_delay_ms);
void c300x_activation_press_release_commands(
    const struct c300x_activation *activation,
    char *press,
    size_t press_len,
    char *release,
    size_t release_len
);

#endif
