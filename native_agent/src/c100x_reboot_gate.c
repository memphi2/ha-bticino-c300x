#include "c100x_activation.h"

#include <stdlib.h>
#include <string.h>

/* A call without an end frame counts as open for at most this long. */
#ifndef C100X_ACTIVATION_CALL_HOLD_MS
#define C100X_ACTIVATION_CALL_HOLD_MS 600000
#endif
#ifndef C100X_ACTIVATION_MIN_UPTIME_MS
#define C100X_ACTIVATION_MIN_UPTIME_MS 120000
#endif

void c100x_activation_door_frame(struct c100x_activation *activation, const char *frame, long long now_ms)
{
    int what;
    if (!activation->enabled || strncmp(frame, "*8*", 3) != 0) {
        return;
    }
    what = atoi(frame + 3);
    /* Locks and lights are no call. */
    if (what >= 19 && what <= 22) {
        return;
    }
    activation->call_frame_ms = now_ms;
    if (what == 1 || what == 2) {
        activation->call_open_ms = now_ms;
    } else if (what == 3) {
        activation->call_open_ms = 0;
    }
}

const char *c100x_reboot_gate(const struct c100x_activation *activation,
    const struct c100x_activation_inputs *inputs)
{
    long long now = inputs->now_ms;
    if (!inputs->reboot_allowed) return "reboot_disabled";
    if (!inputs->door_events) return "call_state_unknown";
    if (activation->call_open_ms && now - activation->call_open_ms < C100X_ACTIVATION_CALL_HOLD_MS) return "call_active";
    if (activation->call_frame_ms && now - activation->call_frame_ms < C100X_ACTIVATION_IDLE_MS) return "call_recent";
    if (inputs->station_busy || c100x_activation_busy(activation)) return "station_busy";
    if (inputs->lease && inputs->lease_blocked) return "display_busy";
    if (now < C100X_ACTIVATION_MIN_UPTIME_MS) return "starting";
    return NULL;
}

