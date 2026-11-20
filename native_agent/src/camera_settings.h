#ifndef C300X_CAMERA_SETTINGS_H
#define C300X_CAMERA_SETTINGS_H

/* The text of the device's bt_answering_machine settings file. Both values
 * count only when each is in the [Answering Machine] section exactly once,
 * as a whole number of up to five digits. */
int c300x_camera_settings_parse(const char *data, int *bitrate_kbps, int *fps);
/* data, which is freed, with both values replaced; NULL when they are not
 * there that way or memory runs out. */
char *c300x_camera_settings_with(char *data, int bitrate_kbps, int fps);

#endif
