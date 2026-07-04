#ifndef C300X_MEDIA_BASE64_H
#define C300X_MEDIA_BASE64_H

#include <stdbool.h>
#include <stddef.h>

bool c300x_media_base64_encode(const unsigned char *data, size_t len, char *out, size_t out_len);
bool c300x_media_base64_decode(const char *text, unsigned char *out, size_t out_len, size_t *decoded_len);

#endif
