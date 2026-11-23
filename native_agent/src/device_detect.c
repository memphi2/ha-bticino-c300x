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

int c300x_device_display_features(void)
{
    return c300x_device_model() == C300X_DEVICE_MODEL_C300X || c300x_device_display_files_patchable();
}
