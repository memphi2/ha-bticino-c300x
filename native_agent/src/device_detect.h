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

/* The camera sends other receivers only its low-resolution stream: C300X
 * 3.0.x, and the C100X, whose bt_av_media builds no high-resolution branch
 * for its board. */
int c300x_device_camera_resolution_fixed(void);

/* The device's own SIP account. The vendor names it after the model:
 * c300x, and c100x on the Classe 100X. */
const char *c300x_device_sip_user(void);

/* The Display patch can edit the display's QML files. Only the Qt 4 display
 * so far; the C100X files are on disk but not patched yet. */
int c300x_device_display_files_patchable(void);

/* The key beep, the display alerts, the display bridge and the ringer mute:
 * offered on every C300X, as before; on the C100X only with display files the
 * Display patch can edit, which it has not yet. */
int c300x_device_display_features(void);

/* The display program can be restarted: BtClass of the C300X, on every
 * firmware. The C100X's program is another one. */
int c300x_device_display_restartable(void);

#endif
