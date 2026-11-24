#include "answering_scope.h"

#include <stdio.h>

#define B(value) ((value) ? "true" : "false")

int c300x_answering_capabilities_json(const struct c300x_config *config, int c100x, char *out, size_t len)
{
    int machine = !c100x;
    int messages = machine && config->answering_machine_messages_enabled;
    int memos = config->memos_enabled;
    int written = snprintf(out, len,
        "\"answering_machine\":{\"supported\":%s,\"status\":%s,\"greeting_message\":%s,"
        "\"messages\":{\"supported\":%s,\"source\":\"local_files\",\"watch\":%s,\"media\":%s,\"delete\":%s}},"
        "\"memos\":{\"supported\":%s,\"text\":true,\"voice\":%s,\"media\":%s,\"source\":\"local_files\","
        "\"watch\":%s,\"delete\":%s,\"write_text\":%s},",
        B(machine), B(machine), B(machine), B(messages),
        B(messages && config->answering_machine_messages_watch), B(messages), B(messages),
        B(memos), B(!c100x), B(memos && !c100x), B(memos && config->memos_watch), B(memos && !c100x), B(memos));
    return written >= 0 && (size_t)written < len;
}
