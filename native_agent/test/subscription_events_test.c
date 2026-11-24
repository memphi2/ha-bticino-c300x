/* A subscription's event list is taken whole or refused, never cut. */
#include <assert.h>
#include <stdarg.h>
#include <stdlib.h>
#include "../src/http.c"

/* Appends or stops the test: no length comes from an unchecked snprintf. */
__attribute__((format(printf, 4, 5)))
static void test_append(char *out, size_t size, size_t *used, const char *format, ...)
{
    va_list args;
    int written;

    if (*used >= size) {
        abort();
    }
    va_start(args, format);
    written = vsnprintf(out + *used, size - *used, format, args);
    va_end(args);
    if (written < 0 || (size_t)written >= size - *used) {
        abort();
    }
    *used += (size_t)written;
}

static int parse(int count, char *body, size_t len)
{
    static struct subscription subscription;
    size_t used = 0;
    test_append(body, len, &used, "{\"events\":[");
    for (int index = 0; index < count; index++) {
        test_append(body, len, &used, "%s\"event_%d\"", index ? ", " : "", index);
    }
    test_append(body, len, &used, " ]}");
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
