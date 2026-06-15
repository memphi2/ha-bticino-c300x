#include "recent_events.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *recent_event_copy(const char *event_json)
{
    size_t event_len = strlen(event_json);
    char *copy;

    if (event_len < C300X_RECENT_EVENT_MAX_LEN) {
        copy = malloc(event_len + 1);
        if (copy == NULL) {
            return NULL;
        }
        memcpy(copy, event_json, event_len + 1);
        return copy;
    }

    copy = malloc(C300X_RECENT_EVENT_MAX_LEN);
    if (copy == NULL) {
        return NULL;
    }
    snprintf(
        copy,
        C300X_RECENT_EVENT_MAX_LEN,
        "{\"type\":\"diagnostic.recent_event_truncated\",\"data\":{\"size\":%zu}}",
        event_len
    );
    return copy;
}

void c300x_recent_events_record(struct c300x_recent_events *events, const char *event_json)
{
    char *copy = recent_event_copy(event_json);

    if (copy == NULL) {
        return;
    }

    if (events->count < C300X_RECENT_EVENTS_CAPACITY) {
        events->items[events->count++] = copy;
        return;
    }

    free(events->items[0]);
    for (int index = 1; index < C300X_RECENT_EVENTS_CAPACITY; index++) {
        events->items[index - 1] = events->items[index];
    }
    events->items[C300X_RECENT_EVENTS_CAPACITY - 1] = copy;
}

void c300x_recent_events_clear(struct c300x_recent_events *events)
{
    for (int index = 0; index < events->count; index++) {
        free(events->items[index]);
        events->items[index] = NULL;
    }
    events->count = 0;
}

int c300x_recent_events_count(const struct c300x_recent_events *events)
{
    return events->count;
}

const char *c300x_recent_events_at(const struct c300x_recent_events *events, int index)
{
    if (index < 0 || index >= events->count) {
        return NULL;
    }
    return events->items[index];
}
