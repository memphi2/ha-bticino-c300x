/* A subscription's event list is taken whole or refused, never cut. */
#include <assert.h>
#include "../src/http.c"

static int parse(int count, char *body, size_t len)
{
    static struct subscription subscription;
    size_t used = (size_t)snprintf(body, len, "{\"events\":[");
    for (int index = 0; index < count; index++) {
        used += (size_t)snprintf(body + used, len - used, "%s\"event_%d\"", index ? ", " : "", index);
    }
    snprintf(body + used, len - used, " ]}");
    json_events_array_range(body, body + strlen(body), &subscription);
    return subscription.event_count;
}

int main(void)
{
    static char body[8192];
    /* Home Assistant subscribes to 23 types today. */
    assert(parse(23, body, sizeof(body)) == 23);
    assert(parse(C300X_MAX_SUBSCRIPTION_EVENTS, body, sizeof(body)) == C300X_MAX_SUBSCRIPTION_EVENTS);
    assert(parse(C300X_MAX_SUBSCRIPTION_EVENTS + 1, body, sizeof(body)) == -1);
    assert(C300X_MAX_SUBSCRIPTION_EVENTS >= 32);
    return 0;
}
