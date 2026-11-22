#ifndef C300X_JSON_UTIL_H
#define C300X_JSON_UTIL_H

#include <stddef.h>

#define C300X_JSON_QUOTED_LEN(value_len) (((value_len) * 6) + 3)

size_t c300x_json_escape_string(const char *value, char *out, size_t out_len);
const char *c300x_json_string(const char *value, char *out, size_t out_len);
const char *c300x_json_string_or_null(const char *value, char *out, size_t out_len);
void c300x_json_string_field(const char *body, const char *field, char *out, size_t out_len);
int c300x_json_bool_field(const char *body, const char *field, int *out);
int c300x_json_int_field(const char *body, const char *field, int *out);
/* 1: whole number, 0: absent, -1: any other value. */
int c300x_json_int_field_checked(const char *body, const char *field, int *out);
int c300x_json_decode_string(const char *value, const char *end,
    char *out, size_t capacity, const char **after);
const char *c300x_json_skip_value(const char *value, const char *end);
int c300x_json_find_member(const char *start, const char *end,
    const char *key, const char **value);
int c300x_json_object_valid(const char *body);
/* 1: decoded, 0: absent, -1: invalid type, encoding or size. */
int c300x_json_string_field_checked(const char *body, const char *field,
    char *out, size_t out_len);

#endif
