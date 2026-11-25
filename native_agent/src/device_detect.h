#ifndef C300X_DEVICE_DETECT_H
#define C300X_DEVICE_DETECT_H

#include <stddef.h>

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

/* How far the model is confirmed. The station names its model itself
 * (<webserver_type> in the vendor's web server file); the display program's
 * name is only the cross-check.
 * ok: both agree. unread: the station named no known model, the display
 * program decided. mismatch: they disagree; the station's own name counts as
 * the model and no display of either kind is written. */
enum c300x_device_model_check {
    C300X_MODEL_CHECK_OK = 0,
    C300X_MODEL_CHECK_UNREAD,
    C300X_MODEL_CHECK_MISMATCH,
};

/* What the agent knows about the station it runs on. Everything that differs
 * between the stations is a question to this profile; nothing else reads the
 * model or the markers on the device. */
struct c300x_device_profile {
    enum c300x_device_model model;
    enum c300x_device_model_check model_check;
    enum c300x_display_kind display;
    /* The camera sends other receivers only its low-resolution stream. */
    int camera_fixed;
};

struct c300x_device_profile c300x_device_profile(void);
const char *c300x_device_model_check_name(enum c300x_device_model_check check);

/* The board as the kernel names it ("BTicino ZIA board HW Rev 3", "BTicino
 * SHARK board (Dig-D/Car-C)") and the article number the vendor's HAL caches
 * ("344642"; none on a C100X). Shown as they are; empty when not readable.
 * Nothing is decided from them. */
#define C300X_DEVICE_BOARD_LEN 96
#define C300X_DEVICE_ARTICLE_LEN 32
void c300x_device_board(char *out, size_t out_len);
void c300x_device_article(char *out, size_t out_len);

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

/* The Display patch exists for this display: the Qt 4 files on disk, or the
 * resource overlay of the Qt 5 display of C300X 3.0.x. Not on the C100X,
 * whose pages come with its own activation. */
int c300x_device_display_files_patchable(void);

/* The key beep, the display alerts, the display bridge and the ringer mute:
 * offered on every C300X, as before; on the C100X once its display adapter
 * was confirmed in a trial boot. */
int c300x_device_display_features(void);
/* Set by the C100X activation from the payload's confirmed status. */
void c300x_device_set_display_adapter_confirmed(int confirmed);

/* The display program can be restarted: BtClass of the C300X, on every
 * firmware. The C100X's program is another one. */
int c300x_device_display_restartable(void);
/* The memo LED is driven only on the C300X; no C100X LED is proven. */
int c300x_device_memo_led_known(void);

#endif
