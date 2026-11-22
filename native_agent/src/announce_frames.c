/* What the frames of the door entry bus mean for the speaker. */
#include "announce.h"
#include "time_util.h"

#include <stdlib.h>
#include <string.h>

int c300x_announce_frame_takes_speaker(const char *frame)
{
    /* A call is set up (ring, intercom, camera view) or answered. Locks,
     * lights, video commands and the end of a call do not take the speaker. */
    return strncmp(frame, "*8*1#", 5) == 0 || strncmp(frame, "*8*2#", 5) == 0;
}

void c300x_announce_door_frame(struct c300x_announce *announce, const char *frame)
{
    long long now = c300x_monotonic_ms();
    int what = strncmp(frame, "*8*", 3) == 0 ? atoi(frame + 3) : -1;

    /* A ring, and every frame of its call while the hold lasts (answer, answering
     * machine, end), except locks and lights, keep the speaker the device's. */
    if (strncmp(frame, "*8*1#1#", 7) == 0 || (announce->ring_until_ms > now && what >= 0
            && (what < 19 || what > 22))) {
        announce->ring_until_ms = now + announce->ring_hold_ms;
        /* A switching off sleeps a fixed time: it starts again after the new hold. */
        if (announce->cleaning) {
            c300x_announce_preempt(announce);
        }
    }
    if (c300x_announce_frame_takes_speaker(frame)) {
        c300x_announce_preempt(announce);
    }
}
