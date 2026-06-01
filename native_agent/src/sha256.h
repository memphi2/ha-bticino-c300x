#ifndef C300X_SHA256_H
#define C300X_SHA256_H

#include <stddef.h>

int c300x_sha256_file_hex(const char *path, char *out, size_t out_len);

#endif
