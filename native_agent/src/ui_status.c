#include "ui_status.h"
#include "json_util.h"

#include <stdio.h>
#include <string.h>

#define C300X_UI_STATUS_ORIGIN_MAX 280

int c300x_ui_status_origin(const char *url, char *out, size_t out_len)
{
    const char *allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:[]";
    size_t scheme_len;
    size_t host_len;

    if (out_len == 0) {
        return 0;
    }
    out[0] = '\0';
    if (url == NULL) {
        return 0;
    }
    if (strncmp(url, "http://", 7) == 0) {
        scheme_len = 7;
    } else if (strncmp(url, "https://", 8) == 0) {
        scheme_len = 8;
    } else {
        return 0;
    }
    host_len = strcspn(url + scheme_len, "/?#");
    /* Anything unusual, user:password@host included, is not shown at all. */
    if (host_len == 0 || strspn(url + scheme_len, allowed) < host_len || scheme_len + host_len >= out_len) {
        return 0;
    }
    memcpy(out, url, scheme_len + host_len);
    out[scheme_len + host_len] = '\0';
    return 1;
}

int c300x_ui_status_json(
    const char *version,
    const char *firmware,
    const char *webhook_url,
    int connected,
    int disabled,
    long last_seen_at,
    long now,
    char *out,
    size_t out_len
)
{
    char origin[C300X_UI_STATUS_ORIGIN_MAX];
    char age[32] = "null";
    char version_json[C300X_JSON_QUOTED_LEN(48)];
    char firmware_json[C300X_JSON_QUOTED_LEN(64)];
    int registered = webhook_url != NULL && webhook_url[0] != '\0';
    int written;

    c300x_ui_status_origin(webhook_url, origin, sizeof(origin));
    if (connected) {
        snprintf(age, sizeof(age), "%ld", now > last_seen_at ? now - last_seen_at : 0L);
    }
    written = snprintf(
        out,
        out_len,
        "{\"ok\":true,\"version\":%s,\"firmware\":%s,\"registered\":%s,\"disabled\":%s,\"home_assistant\":\"%s\",\"last_contact_age\":%s}\n",
        c300x_json_string(version, version_json, sizeof(version_json)),
        c300x_json_string(firmware, firmware_json, sizeof(firmware_json)),
        registered ? "true" : "false",
        disabled ? "true" : "false",
        origin,
        age
    );
    return written > 0 && (size_t)written < out_len;
}
