#ifndef C300X_SETTING_STATE_H
#define C300X_SETTING_STATE_H

#include <stdint.h>

enum c300x_setting_transition {
    C300X_SETTING_SAME,
    C300X_SETTING_INITIAL,
    C300X_SETTING_CHANGED,
    C300X_SETTING_AVAILABILITY
};

struct c300x_setting_state {
    int known, available;
    uint64_t last_valid;
};

/* Confirmed values or content signatures only, never repeatable action events. */
static inline enum c300x_setting_transition c300x_setting_observe(
    struct c300x_setting_state *state, int available, uint64_t value)
{
    enum c300x_setting_transition transition = C300X_SETTING_SAME;
    if (!available) {
        if (state->available) transition = C300X_SETTING_AVAILABILITY;
        state->available = 0;
        return transition;
    }
    if (!state->known) transition = C300X_SETTING_INITIAL;
    else if (state->last_valid != value) transition = C300X_SETTING_CHANGED;
    else if (!state->available) transition = C300X_SETTING_AVAILABILITY;
    state->known = state->available = 1;
    state->last_valid = value;
    return transition;
}

#endif
