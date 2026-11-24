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

int c300x_label_qt5_state_ok(const char *body, int applying)
{
    char overlay[32] = "";
    int running = 0, patched = 0;
    c300x_json_string_field(body, "qt5_overlay", overlay, sizeof(overlay));
    if (overlay[0] == '\0') return 1; /* Legacy Qt4 status contract. */
    if (!c300x_json_bool_field(body, "gui_running", &running) || !running
        || !c300x_json_bool_field(body, "media_user_label_patched", &patched)
        || patched != applying) return 0;
    /* Removing a label must not reactivate an unrelated quarantined overlay. */
    return strcmp(overlay, "active") == 0
        || (!applying && (strcmp(overlay, "off") == 0 || strcmp(overlay, "failed") == 0));
}

int c300x_label_result_ok(char *output, int applying)
{
    const char *body = c300x_label_trim(output);
    char error[32] = "";
    int ok = 0;
    /* Preserve legacy restore scripts which only report their exit status. */
    if (body[0] != '{') return !applying;
    if (!c300x_json_object_valid(body)) return 0;
    /* A display the agent does not know keeps its own texts: no label to set. */
    c300x_json_string_field(body, "error", error, sizeof(error));
    if (applying && strcmp(error, "display_unsupported") == 0) return 1;
    return c300x_json_bool_field(body, "ok", &ok) && ok
        && c300x_label_qt5_state_ok(body, applying);
}
