#ifndef C300X_JSON_UTIL_H
#define C300X_JSON_UTIL_H

#include <stddef.h>

size_t c300x_json_escape_string(const char *value, char *out, size_t out_len);
const char *c300x_json_string(const char *value, char *out, size_t out_len);
const char *c300x_json_string_or_null(const char *value, char *out, size_t out_len);
void c300x_json_string_field(const char *body, const char *field, char *out, size_t out_len);
int c300x_json_bool_field(const char *body, const char *field, int *out);
int c300x_json_int_field(const char *body, const char *field, int *out);

#endif
