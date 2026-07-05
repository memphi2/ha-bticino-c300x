#include "local_action_events.h"

#include "string_util.h"

#include <string.h>

static int is_local_action_event(const char *type)
{
    return type != NULL
        && (
            strcmp(type, "door_unlock.started") == 0
            || strcmp(type, "door_unlock.ended") == 0
            || strcmp(type, "stair_light.activated") == 0
            || strcmp(type, "stair_light.released") == 0
        );
}

int c300x_local_action_event_is_duplicate(
    struct c300x_local_action_events *events,
    const char *type,
    const char *address,
    long long now_ms
)
{
    if (events == NULL || !is_local_action_event(type) || address == NULL) {
        return 0;
    }
    for (int index = 0; index < C300X_LOCAL_ACTION_EVENT_HISTORY; index++) {
        const struct c300x_local_action_event_marker *marker = &events->items[index];
        if (
            marker->occurred_ms > 0
            && now_ms >= marker->occurred_ms
            && now_ms - marker->occurred_ms < C300X_LOCAL_ACTION_EVENT_DEDUPE_MS
            && strcmp(marker->type, type) == 0
            && strcmp(marker->address, address) == 0
        ) {
            return 1;
        }
    }
    c300x_local_action_event_remember(events, type, address, now_ms);
    return 0;
}

void c300x_local_action_event_remember(
    struct c300x_local_action_events *events,
    const char *type,
    const char *address,
    long long occurred_ms
)
{
    struct c300x_local_action_event_marker *marker;
    int index;

    if (events == NULL || !is_local_action_event(type) || address == NULL) {
        return;
    }
    index = events->next_index;
    if (index < 0 || index >= C300X_LOCAL_ACTION_EVENT_HISTORY) {
        index = 0;
    }
    marker = &events->items[index];
    marker->occurred_ms = occurred_ms;
    c300x_copy_string(marker->type, sizeof(marker->type), type);
    c300x_copy_string(marker->address, sizeof(marker->address), address);
    events->next_index = (index + 1) % C300X_LOCAL_ACTION_EVENT_HISTORY;
}
