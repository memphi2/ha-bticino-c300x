#ifndef C300X_DEVICE_MEDIA_H
#define C300X_DEVICE_MEDIA_H

#include <stdbool.h>

struct c300x_config;

bool c300x_device_media_start(const struct c300x_config *config);
bool c300x_device_media_takeover(const struct c300x_config *config);
void c300x_device_media_stop(const struct c300x_config *config);

#endif
