/* /ui/memos lists the memos deleted through the agent. */
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../src/memo_deleted.h"

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

static const char *finish(void)
{
    static char body[4096];
    size_t used = 0;
    body[0] = '\0';
    assert(c300x_memo_deleted_finish_json(body, sizeof(body), &used));
    return body;
}

int main(void)
{
    char name[32], expected[4096];
    size_t used = 0;
    assert(strcmp(finish(), "],\"deleted\":[]}\n") == 0);
    c300x_memo_deleted_add("text", "memo_12");
    c300x_memo_deleted_add("voice", "memo_3");
    assert(strcmp(finish(), "],\"deleted\":[\"text/memo_12\",\"voice/memo_3\"]}\n") == 0);
    /* Deleted twice: listed once, as the newest. */
    c300x_memo_deleted_add("text", "memo_12");
    assert(strcmp(finish(), "],\"deleted\":[\"voice/memo_3\",\"text/memo_12\"]}\n") == 0);
    /* The station reuses the number: that memo is no longer deleted. */
    c300x_memo_deleted_seen("text", "memo_12");
    c300x_memo_deleted_seen("text", "memo_99");
    assert(strcmp(finish(), "],\"deleted\":[\"voice/memo_3\"]}\n") == 0);
    /* Only the last 32 are kept, oldest first. */
    for (int index = 0; index < 40; index++) {
        snprintf(name, sizeof(name), "memo_%d", index);
        c300x_memo_deleted_add("text", name);
    }
    used = 0;
    test_append(expected, sizeof(expected), &used, "],\"deleted\":[");
    for (int index = 8; index < 40; index++) {
        test_append(expected, sizeof(expected), &used, "%s\"text/memo_%d\"", index > 8 ? "," : "", index);
    }
    test_append(expected, sizeof(expected), &used, "]}\n");
    assert(strcmp(finish(), expected) == 0);
    /* A body without room fails instead of cutting the JSON. */
    char small[40];
    used = 0;
    assert(!c300x_memo_deleted_finish_json(small, sizeof(small), &used));
    return 0;
}
