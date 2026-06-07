#ifndef C300X_SHA256_H
#define C300X_SHA256_H

#include <stddef.h>

#define C300X_SHA256_DIGEST_LEN 32

int c300x_sha256_file_hex(const char *path, char *out, size_t out_len);
int c300x_sha256_strings3(
    const char *part1,
    const char *part2,
    const char *part3,
    unsigned char digest[C300X_SHA256_DIGEST_LEN]
);

#endif
