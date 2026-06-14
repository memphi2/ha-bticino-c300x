#ifndef C300X_RECENT_EVENTS_H
#define C300X_RECENT_EVENTS_H

#define C300X_RECENT_EVENTS_CAPACITY 16
#define C300X_RECENT_EVENT_MAX_LEN 2048

struct c300x_recent_events {
    char *items[C300X_RECENT_EVENTS_CAPACITY];
    int count;
};

void c300x_recent_events_record(struct c300x_recent_events *events, const char *event_json);
void c300x_recent_events_clear(struct c300x_recent_events *events);
int c300x_recent_events_count(const struct c300x_recent_events *events);
const char *c300x_recent_events_at(const struct c300x_recent_events *events, int index);

#endif
