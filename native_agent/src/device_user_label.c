#include "device_user_label.h"
#include "json_util.h"

#include <ctype.h>
#include <string.h>

const char *c300x_label_trim(char *value)
{
    char *start = value, *end;
    while (*start != '\0' && isspace((unsigned char)*start)) {
        start++;
    }
    end = start + strlen(start);
    while (end > start && isspace((unsigned char)end[-1])) {
        end--;
    }
    *end = '\0';
    return start;
}

int c300x_label_result_ok(char *output, int applying)
{
    const char *body = c300x_label_trim(output);
    int ok = 0;
    /* Preserve legacy restore scripts which only report their exit status. */
    if (body[0] != '{') return !applying;
    if (!c300x_json_object_valid(body)) return 0;
    return c300x_json_bool_field(body, "ok", &ok) && ok;
}
