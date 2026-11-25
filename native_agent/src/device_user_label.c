#include "device_user_label.h"
#include "http_maintenance.h"
#include "http_util.h"
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

int c300x_label_job_start(struct c300x_command_job *job, const char *script,
    int restoring, char *out, size_t out_len)
{
    if (!c300x_command_job_start_capture(job, script,
            restoring ? "media-user-label-restore" : "media-user-label-apply",
            out, out_len, C300X_QML_WRITE_TIMEOUT_MS)) {
        return 0;
    }
    job->term_grace_ms = C300X_QML_WRITE_TERM_GRACE_MS;
    return 1;
}

void c300x_label_send_timeout(int fd, int exit_status)
{
    c300x_http_send_json(fd, 504, "Gateway Timeout", exit_status == 130
        ? "{\"ok\":false,\"error\":\"media_user_label_timeout\",\"rolled_back\":true}\n"
        : "{\"ok\":false,\"error\":\"media_user_label_timeout\",\"rolled_back\":false}\n");
}
