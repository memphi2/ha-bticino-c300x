#include "string_util.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

void c300x_copy_string(char *dest, size_t dest_len, const char *value)
{
    const char *source = value != NULL ? value : "";
    size_t len;

    if (dest == NULL || dest_len == 0) {
        return;
    }
    len = strlen(source);
    if (len >= dest_len) {
        len = dest_len - 1;
    }
    if (len > 0) {
        memcpy(dest, source, len);
    }
    dest[len] = '\0';
}

int c300x_join_path(char *dest, size_t dest_len, const char *path, const char *name)
{
    size_t path_len;
    size_t name_len;

    if (dest == NULL || path == NULL || name == NULL || dest_len == 0) {
        return 0;
    }
    path_len = strlen(path);
    name_len = strlen(name);
    if (path_len + 1 + name_len >= dest_len) {
        return 0;
    }
    memcpy(dest, path, path_len);
    dest[path_len] = '/';
    memcpy(dest + path_len + 1, name, name_len + 1);
    return 1;
}

int c300x_join_suffix(char *dest, size_t dest_len, const char *base, const char *suffix)
{
    size_t base_len;
    size_t suffix_len;

    if (dest == NULL || base == NULL || suffix == NULL || dest_len == 0) {
        return 0;
    }
    base_len = strlen(base);
    suffix_len = strlen(suffix);
    if (base_len + suffix_len >= dest_len) {
        return 0;
    }
    memcpy(dest, base, base_len);
    memcpy(dest + base_len, suffix, suffix_len + 1);
    return 1;
}

int c300x_appendf(char *dest, size_t dest_len, size_t *used, const char *format, ...)
{
    va_list args;
    size_t remaining;
    int written;

    if (dest == NULL || used == NULL || format == NULL || *used >= dest_len) {
        return 0;
    }
    remaining = dest_len - *used;
    va_start(args, format);
    written = vsnprintf(dest + *used, remaining, format, args);
    va_end(args);
    if (written < 0) {
        return 0;
    }
    if ((size_t)written >= remaining) {
        *used = dest_len;
        return 0;
    }
    *used += (size_t)written;
    return 1;
}
