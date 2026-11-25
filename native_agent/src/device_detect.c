#include "device_detect.h"

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

struct c300x_device_profile c300x_device_profile(void)
{
    struct c300x_device_profile profile = {C300X_DEVICE_MODEL_C300X, C300X_DISPLAY_QT4_ONDISK, 0};

    /* A known C100X must never receive the C300X Qt 4 file patch, whatever
     * libraries it carries. */
    if (access(C300X_C100X_DISPLAY_MARKER, F_OK) == 0) {
        profile.model = C300X_DEVICE_MODEL_C100X;
        profile.display = C300X_DISPLAY_QT5_ONDISK;
    } else if (access(C300X_QT5_DISPLAY_MARKER, F_OK) == 0) {
        profile.display = C300X_DISPLAY_QT5_RCC;
    }
    profile.camera_fixed = profile.display != C300X_DISPLAY_QT4_ONDISK;
    return profile;
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
    return c300x_device_display_kind() != C300X_DISPLAY_QT5_ONDISK;
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
