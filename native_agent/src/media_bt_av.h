#ifndef C300X_MEDIA_BT_AV_H
#define C300X_MEDIA_BT_AV_H

#include <stdbool.h>

struct c300x_config;

bool c300x_media_bt_av_start(const struct c300x_config *config);
bool c300x_media_bt_av_takeover(const struct c300x_config *config);
void c300x_media_bt_av_stop(void);

#endif
