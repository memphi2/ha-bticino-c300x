#include "firmware_version.h"
#include "file_io.h"
#include "string_util.h"

#include <ctype.h>
#include <string.h>

#ifndef C300X_FIRMWARE_INFO_XML
#define C300X_FIRMWARE_INFO_XML "/home/bticino/sp/dbfiles_ws.xml"
#endif

static int firmware_version_is_safe(const char *value, size_t len)
{
    if (len == 0 || len >= C300X_MAX_VERSION_LEN) {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        unsigned char ch = (unsigned char)value[index];
        if (
            (ch >= '0' && ch <= '9')
            || (ch >= 'A' && ch <= 'Z')
            || (ch >= 'a' && ch <= 'z')
            || ch == '.'
            || ch == '-'
            || ch == '_'
        ) {
            continue;
        }
        return 0;
    }
    return 1;
}

static int read_firmware_from_webserver_db(char *out, size_t out_len)
{
    char document[4096];
    int truncated = 0;
    const char *start;
    const char *end;
    const char *open_tag = "<ver_webserver>";
    const char *close_tag = "</ver_webserver>";
    size_t len;

    if (!read_bounded_text_file(C300X_FIRMWARE_INFO_XML, document, sizeof(document), &truncated) || truncated) {
        return 0;
    }
    start = strstr(document, open_tag);
    if (start == NULL) {
        return 0;
    }
    start += strlen(open_tag);
    end = strstr(start, close_tag);
    if (end == NULL || end <= start) {
        return 0;
    }
    while (start < end && isspace((unsigned char)*start)) {
        start++;
    }
    while (end > start && isspace((unsigned char)end[-1])) {
        end--;
    }
    len = (size_t)(end - start);
    if (!firmware_version_is_safe(start, len) || len >= out_len) {
        return 0;
    }
    memcpy(out, start, len);
    out[len] = '\0';
    return 1;
}

void resolve_device_firmware(
    const struct c300x_config *config,
    char *out,
    size_t out_len
)
{
    if (out_len == 0) {
        return;
    }
    out[0] = '\0';
    if (config != NULL && config->device_firmware[0] != '\0') {
        c300x_copy_string(out, out_len, config->device_firmware);
        return;
    }
    (void)read_firmware_from_webserver_db(out, out_len);
}
