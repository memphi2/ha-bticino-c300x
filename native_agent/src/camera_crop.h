#ifndef C300X_CAMERA_CROP_H
#define C300X_CAMERA_CROP_H

/*
 * The cut of the camera picture for the high stream, in the <crop> block of
 * the device's stack_open.xml: left, top, width, height. The device uses it
 * when Width is more than 1.5 times Height (800x480 from the factory) and
 * shows the cut stretched over the whole display.
 */

/* All four count only when the block is there once with each tag once, as a
 * whole number of up to four digits. */
int c300x_camera_crop_parse(const char *data, int crop[4]);
/* data, which is freed, with the four numbers replaced; NULL when they are
 * not there that way or memory runs out. */
char *c300x_camera_crop_with(char *data, const int crop[4]);

#endif
