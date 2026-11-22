#ifndef C300X_DEVICE_DETECT_H
#define C300X_DEVICE_DETECT_H

enum c300x_device_model {
    C300X_DEVICE_MODEL_C300X = 0,
    C300X_DEVICE_MODEL_C100X,
};

/* qt4_ondisk: C300X 1.7.x/2.0.x, Qt 4 with QML files on disk.
 * qt5_rcc: C300X 3.0.x, Qt 5 with the QML built into the display program.
 * qt5_ondisk: C100X, Qt 5 with QML files on disk. */
enum c300x_display_kind {
    C300X_DISPLAY_QT4_ONDISK = 0,
    C300X_DISPLAY_QT5_RCC,
    C300X_DISPLAY_QT5_ONDISK,
};

enum c300x_device_model c300x_device_model(void);
enum c300x_display_kind c300x_device_display_kind(void);
const char *c300x_device_model_name(enum c300x_device_model model);
const char *c300x_display_kind_name(enum c300x_display_kind kind);

/* The camera sends other receivers only its low-resolution stream. True on
 * C300X 3.0.x; on the C100X kept until a device shows otherwise. */
int c300x_device_camera_resolution_fixed(void);

/* The Display patch can edit the display's QML files. Only the Qt 4 display
 * so far; the C100X files are on disk but not patched yet. */
int c300x_device_display_files_patchable(void);

#endif
