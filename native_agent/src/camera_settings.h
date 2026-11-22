#ifndef C300X_CAMERA_SETTINGS_H
#define C300X_CAMERA_SETTINGS_H

/* The camera values in the text of the device's bt_answering_machine
 * settings file: those of the high-resolution stream, or of the low one,
 * the only stream firmware 3.0.x sends. */
struct c300x_camera_values {
    int bitrate_kbps;
    int fps;
    int width;
    int height;
    /* High stream: the cut of the picture in stack_open.xml (left, top,
     * width, height); 0 for the low stream. Not part of this file. */
    int crop[4];
};

/* All four count only when each is in the [Answering Machine] section
 * exactly once, as a whole number of up to five digits. */
int c300x_camera_settings_parse(const char *data, int low, struct c300x_camera_values *values);
/* data, which is freed, with the four values replaced; NULL when they are
 * not there that way or memory runs out. */
char *c300x_camera_settings_with(char *data, int low, const struct c300x_camera_values *values);

#endif
