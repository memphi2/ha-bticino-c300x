#include "device_detect.h"

#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <stdatomic.h>
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
/* The vendor's web server file names the model, the kernel the board, the
 * vendor's HAL caches the article number. */
#ifndef C300X_DEVICE_INFO_XML
#define C300X_DEVICE_INFO_XML "/home/bticino/sp/dbfiles_ws.xml"
#endif
#ifndef C300X_DEVICE_CPUINFO
#define C300X_DEVICE_CPUINFO "/proc/cpuinfo"
#endif
#ifndef C300X_DEVICE_TREE_MODEL
#define C300X_DEVICE_TREE_MODEL "/sys/firmware/devicetree/base/model"
#endif
#ifndef C300X_DEVICE_ARTICLE_FILE
#define C300X_DEVICE_ARTICLE_FILE "/var/tmp/flags/codename"
#endif

/* Reads the start of a file; a longer file is cut, which the callers allow:
 * what they look for stands at its start. */
static size_t read_start(const char *path, char *out, size_t len)
{
    size_t used = 0;
    int fd = open(path, O_RDONLY | O_CLOEXEC);

    out[0] = '\0';
    if (fd < 0) {
        return 0;
    }
    while (used + 1 < len) {
        ssize_t count = read(fd, out + used, len - 1 - used);
        if (count < 0 && errno == EINTR) {
            continue;
        }
        if (count <= 0) {
            used = count < 0 ? 0 : used;
            break;
        }
        used += (size_t)count;
    }
    close(fd);
    out[used] = '\0';
    return used;
}

/* Copies printable ASCII without white space and the given padding at both
 * ends; anything else, or a value that does not fit, leaves out empty. */
static void copy_trimmed(const char *start, const char *end, const char *padding, char *out, size_t out_len)
{
    out[0] = '\0';
    while (start < end && (isspace((unsigned char)*start) || strchr(padding, *start) != NULL)) {
        start++;
    }
    while (end > start && (isspace((unsigned char)end[-1]) || strchr(padding, end[-1]) != NULL)) {
        end--;
    }
    if (end == start || (size_t)(end - start) >= out_len) {
        return;
    }
    for (const char *ch = start; ch < end; ch++) {
        if ((unsigned char)*ch < 0x20 || (unsigned char)*ch > 0x7e) {
            return;
        }
    }
    memcpy(out, start, (size_t)(end - start));
    out[end - start] = '\0';
}

/* 1 C300X, 2 C100X, 3 the station names no known model. The file is part of
 * the firmware and does not change while the agent runs: read once. */
static int station_model(void)
{
    static atomic_int cached;
    char document[4096], value[16] = "";
    const char *start, *end;
    int model = atomic_load(&cached);

    if (model != 0) {
        return model;
    }
    model = 3;
    if (read_start(C300X_DEVICE_INFO_XML, document, sizeof(document)) > 0
        && (start = strstr(document, "<webserver_type>")) != NULL
        && (end = strstr(start, "</webserver_type>")) != NULL) {
        copy_trimmed(start + strlen("<webserver_type>"), end, "", value, sizeof(value));
        model = strcmp(value, "C300X") == 0 ? 1 : strcmp(value, "C100X") == 0 ? 2 : 3;
    }
    atomic_store(&cached, model);
    return model;
}

struct c300x_device_profile c300x_device_profile(void)
{
    struct c300x_device_profile profile = {
        C300X_DEVICE_MODEL_C300X, C300X_MODEL_CHECK_OK, C300X_DISPLAY_QT4_ONDISK, 0};
    int named = station_model();
    int c100x_program = access(C300X_C100X_DISPLAY_MARKER, F_OK) == 0;

    if (named == 3) {
        profile.model_check = C300X_MODEL_CHECK_UNREAD;
    } else if ((named == 2) != c100x_program) {
        profile.model_check = C300X_MODEL_CHECK_MISMATCH;
    }
    /* Where the station's own name is missing or disagrees, its display
     * program decides model and display, as it always did. The disagreement
     * is reported; neither the Display patch nor the C100X activation is
     * written on such a station. */
    profile.model = c100x_program ? C300X_DEVICE_MODEL_C100X : C300X_DEVICE_MODEL_C300X;
    if (c100x_program) {
        profile.display = C300X_DISPLAY_QT5_ONDISK;
    } else if (access(C300X_QT5_DISPLAY_MARKER, F_OK) == 0) {
        profile.display = C300X_DISPLAY_QT5_RCC;
    }
    profile.camera_fixed = profile.display != C300X_DISPLAY_QT4_ONDISK;
    return profile;
}

const char *c300x_device_model_check_name(enum c300x_device_model_check check)
{
    return check == C300X_MODEL_CHECK_MISMATCH ? "mismatch"
        : check == C300X_MODEL_CHECK_UNREAD ? "unread" : "ok";
}

void c300x_device_board(char *out, size_t out_len)
{
    char text[4096];

    if (out_len == 0) {
        return;
    }
    out[0] = '\0';
    if (read_start(C300X_DEVICE_CPUINFO, text, sizeof(text)) > 0) {
        for (const char *line = text; line != NULL; ) {
            const char *end = line + strcspn(line, "\n");
            if (strncmp(line, "Hardware", 8) == 0) {
                const char *value = line + 8 + strspn(line + 8, " \t");
                if (*value == ':') {
                    copy_trimmed(value + 1, end, "", out, out_len);
                }
                break;
            }
            line = *end == '\n' ? end + 1 : NULL;
        }
    }
    if (out[0] == '\0' && read_start(C300X_DEVICE_TREE_MODEL, text, sizeof(text)) > 0) {
        copy_trimmed(text, text + strlen(text), "", out, out_len);
    }
}

void c300x_device_article(char *out, size_t out_len)
{
    char text[64];

    if (out_len == 0) {
        return;
    }
    out[0] = '\0';
    if (read_start(C300X_DEVICE_ARTICLE_FILE, text, sizeof(text)) > 0) {
        copy_trimmed(text, text + strlen(text), "$", out, out_len);
    }
}

enum c300x_device_model c300x_device_model(void)
{
    return c300x_device_profile().model;
}

enum c300x_display_kind c300x_device_display_kind(void)
{
    return c300x_device_profile().display;
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
    return c300x_device_profile().camera_fixed;
}

const char *c300x_device_sip_user(void)
{
    return c300x_device_model() == C300X_DEVICE_MODEL_C100X ? "c100x" : "c300x";
}

int c300x_device_display_restartable(void)
{
    return c300x_device_model() == C300X_DEVICE_MODEL_C300X;
}

int c300x_device_memo_led_known(void)
{
    return c300x_device_model() == C300X_DEVICE_MODEL_C300X;
}

int c300x_device_display_files_patchable(void)
{
    struct c300x_device_profile profile = c300x_device_profile();
    return profile.display != C300X_DISPLAY_QT5_ONDISK && profile.model_check != C300X_MODEL_CHECK_MISMATCH;
}

static int display_adapter_confirmed;

void c300x_device_set_display_adapter_confirmed(int confirmed)
{
    display_adapter_confirmed = confirmed != 0;
}

int c300x_device_display_features(void)
{
    return c300x_device_profile().model == C300X_DEVICE_MODEL_C300X || display_adapter_confirmed;
}
