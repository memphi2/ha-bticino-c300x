#include "media_session_guard.h"

#include <stddef.h>

void c300x_media_session_guard_note_stop(c300x_media_session_guard_t *guard, bool explicit_stop)
{
    if (guard != NULL && explicit_stop) {
        guard->explicit_stop = true;
    }
}

void c300x_media_session_guard_clear(c300x_media_session_guard_t *guard)
{
    if (guard != NULL) {
        guard->explicit_stop = false;
    }
}

bool c300x_media_session_guard_blocks_start(const c300x_media_session_guard_t *guard)
{
    return guard != NULL && guard->explicit_stop;
}
