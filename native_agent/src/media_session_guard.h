#ifndef C300X_MEDIA_SESSION_GUARD_H
#define C300X_MEDIA_SESSION_GUARD_H

#include <stdbool.h>

typedef struct {
    bool explicit_stop;
} c300x_media_session_guard_t;

void c300x_media_session_guard_note_stop(c300x_media_session_guard_t *guard, bool explicit_stop);
void c300x_media_session_guard_clear(c300x_media_session_guard_t *guard);
bool c300x_media_session_guard_blocks_start(const c300x_media_session_guard_t *guard);

#endif
