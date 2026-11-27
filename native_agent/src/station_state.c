#include "station_state.h"

#include <stdio.h>
#include <string.h>

int c300x_station_state_parse(const char *frame, int *code)
{
    int x, y, consumed = 0;

    if (frame == NULL || sscanf(frame, "*#8**35*%d*%d*%d##%n", code, &x, &y, &consumed) != 3
        || consumed == 0 || frame[consumed] != '\0' || *code < 0 || *code > 99) {
        return 0;
    }
    return 1;
}

/* From the captures and bt_answering_machine's callers of its state sender:
 * 1 a call is set up (ring or view), 2 the ringtone plays, 3 a view without
 * a ring, 4 the ringtone is over (timed out or muted) and the call still
 * waits, 6 a conversation, 7 the answering machine took the call (*8*67),
 * 8 it plays its greeting, 9 it records the visitor, 0 nothing. */
const char *c300x_station_state_name(int code)
{
    static const char *const names[] = {
        "idle", "setup", "ringing", "viewing", "waiting", NULL, "conversation",
        "answering_machine", "greeting", "recording",
    };

    return code >= 0 && code < (int)(sizeof(names) / sizeof(names[0])) ? names[code] : NULL;
}
