#ifndef C300X_LOCAL_ACTION_EVENTS_H
#define C300X_LOCAL_ACTION_EVENTS_H

#include "c300x_agent.h"

#define C300X_LOCAL_ACTION_EVENT_DEDUPE_MS 1000
#define C300X_LOCAL_ACTION_EVENT_HISTORY 8

struct c300x_local_action_event_marker {
    long long occurred_ms;
    char type[64];
    char address[C300X_MAX_ADDRESS_LEN];
};

struct c300x_local_action_events {
    int next_index;
    struct c300x_local_action_event_marker items[C300X_LOCAL_ACTION_EVENT_HISTORY];
};

int c300x_local_action_event_is_duplicate(
    struct c300x_local_action_events *events,
    const char *type,
    const char *address,
    long long now_ms
);

void c300x_local_action_event_remember(
    struct c300x_local_action_events *events,
    const char *type,
    const char *address,
    long long occurred_ms
);

#endif
