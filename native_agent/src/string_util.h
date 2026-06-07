#ifndef C300X_STRING_UTIL_H
#define C300X_STRING_UTIL_H

#include <stddef.h>

void c300x_copy_string(char *dest, size_t dest_len, const char *value);
int c300x_join_path(char *dest, size_t dest_len, const char *path, const char *name);
int c300x_join_suffix(char *dest, size_t dest_len, const char *base, const char *suffix);
int c300x_appendf(char *dest, size_t dest_len, size_t *used, const char *format, ...);

#endif
