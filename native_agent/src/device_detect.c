#include "device_detect.h"

#include "c300x_agent.h"
#include "file_io.h"
#include "string_util.h"

#include <ctype.h>
#include <string.h>
#include <unistd.h>

/* The Qt 5 library marks a Qt 5 display, not a missing QML folder: a folder
 * can be missing on an older device for other reasons. The display program's
 * name tells the C100X from the C300X; the hostname can be changed. */
#ifndef C300X_QT5_DISPLAY_MARKER
#define C300X_QT5_DISPLAY_MARKER "/usr/lib/libQt5Core.so.5"
#endif
#ifndef C300X_C100X_DISPLAY_MARKER
#define C300X_C100X_DISPLAY_MARKER "/home/bticino/bin/gui/BtClass100"
#endif
#ifndef C300X_FIRMWARE_INFO_XML
#define C300X_FIRMWARE_INFO_XML "/home/bticino/sp/dbfiles_ws.xml"
#endif

enum c300x_device_model c300x_device_model(void)
{
    return access(C300X_C100X_DISPLAY_MARKER, F_OK) == 0
        ? C300X_DEVICE_MODEL_C100X
        : C300X_DEVICE_MODEL_C300X;
}

enum c300x_display_kind c300x_device_display_kind(void)
{
    /* A known C100X must never receive the C300X Qt 4 file patch. */
    if (c300x_device_model() == C300X_DEVICE_MODEL_C100X) {
        return C300X_DISPLAY_QT5_ONDISK;
    }
    if (access(C300X_QT5_DISPLAY_MARKER, F_OK) != 0) {
        return C300X_DISPLAY_QT4_ONDISK;
    }
    return C300X_DISPLAY_QT5_RCC;
}

const char *c300x_device_model_name(enum c300x_device_model model)
{
    return model == C300X_DEVICE_MODEL_C100X ? "C100X" : "C300X";
}

const char *c300x_display_kind_name(enum c300x_display_kind kind)
{
    switch (kind) {
    case C300X_DISPLAY_QT5_RCC:
        return "qt5_rcc";
    case C300X_DISPLAY_QT5_ONDISK:
        return "qt5_ondisk";
    case C300X_DISPLAY_QT4_ONDISK:
    default:
        return "qt4_ondisk";
    }
}

int c300x_device_camera_resolution_fixed(void)
{
    return c300x_device_model() == C300X_DEVICE_MODEL_C100X
        || c300x_device_display_kind() != C300X_DISPLAY_QT4_ONDISK;
}

const char *c300x_device_sip_user(void)
{
    return c300x_device_model() == C300X_DEVICE_MODEL_C100X ? "c100x" : "c300x";
}

int c300x_device_display_restartable(void)
{
    return c300x_device_model() == C300X_DEVICE_MODEL_C300X;
}

int c300x_device_display_files_patchable(void)
{
    return c300x_device_display_kind() == C300X_DISPLAY_QT4_ONDISK;
}

static int firmware_version_is_safe(const char *value, size_t len)
{
    if (len == 0 || len >= C300X_MAX_VERSION_LEN) {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        unsigned char ch = (unsigned char)value[index];
        if (!isalnum(ch) && ch != '.' && ch != '-' && ch != '_') {
            return 0;
        }
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

void c300x_device_firmware(const char *configured, char *out, size_t out_len)
{
    if (out_len == 0) {
        return;
    }
    out[0] = '\0';
    if (configured != NULL && configured[0] != '\0') {
        c300x_copy_string(out, out_len, configured);
        return;
    }
    (void)read_firmware_from_webserver_db(out, out_len);
}
