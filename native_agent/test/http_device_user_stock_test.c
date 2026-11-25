/* Use the real detector with offline firmware paths, retaining device-write stubs. */
#define c300x_device_display_files_patchable fixture_display_files_patchable
#include "http_device_user_test.c"
#undef c300x_device_display_files_patchable
#define C300X_C100X_DISPLAY_MARKER getenv("C300X_QML_C100X_MARKER")
#define C300X_QT5_DISPLAY_MARKER getenv("C300X_QML_QT5_MARKER")
#include "../src/device_detect.c"
