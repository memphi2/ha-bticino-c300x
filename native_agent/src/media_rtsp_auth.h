#ifndef C300X_MEDIA_RTSP_AUTH_H
#define C300X_MEDIA_RTSP_AUTH_H

#include <stdbool.h>

struct c300x_config;

#define C300X_RTSP_AUTH_CHALLENGE "WWW-Authenticate: Basic realm=\"C300X\"\r\n"

bool c300x_media_rtsp_authorized(const struct c300x_config *config, const char *request);

#endif
