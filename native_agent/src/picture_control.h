#ifndef C300X_PICTURE_CONTROL_H
#define C300X_PICTURE_CONTROL_H

#include "c300x_agent.h"
#include "http_request.h"

enum picture_field { PICTURE_NONE, PICTURE_READ, PICTURE_BRIGHTNESS, PICTURE_CONTRAST, PICTURE_SATURATION };

/* The station's own picture settings, changed and read with its own bus
 * frames: bt_av_media applies a change to the running video and announces it,
 * and bt_answering_machine stores it for the unit of the running call, so the
 * station applies it again to every later video of that unit. Both only act
 * while a video runs. */
#define PICTURE_STATUS_REQUEST "*#7**20##"

/* The stations whose vendor programs answer these frames, by the runtime
 * model and the firmware read from the station itself. */
int picture_controls_supported(void);
/* *#7**#<5|6|7>*<value>## for one control, 0 through 100. */
int picture_write_frame(enum picture_field field, int value, char *out, size_t out_len);
/* *#7**20*<brightness>*<contrast>*<saturation>*<quality>*<sharpness>##, each
 * 0 through 100: the first three into values. */
int picture_status_values(const char *frame, int values[3]);
void picture_request(const struct c300x_config *config, int fd, const struct request *request);

#endif
