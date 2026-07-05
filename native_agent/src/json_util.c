#include "json_util.h"

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

size_t c300x_json_escape_string(const char *value, char *out, size_t out_len)
{
    const char *source = value != NULL ? value : "";
    size_t used = 0;

    if (out == NULL || out_len == 0) {
        return 0;
    }
    for (size_t index = 0; source[index] != '\0' && used + 1 < out_len; index++) {
        unsigned char ch = (unsigned char)source[index];
        if (ch == '\\' || ch == '"') {
            if (used + 2 >= out_len) {
                break;
            }
            out[used++] = '\\';
            out[used++] = (char)ch;
            continue;
        }
        if (ch < 0x20) {
            if (used + 6 >= out_len) {
                break;
            }
            used += (size_t)snprintf(out + used, out_len - used, "\\u%04x", ch);
            continue;
        }
        out[used++] = (char)ch;
    }
    out[used] = '\0';
    return used;
}

const char *c300x_json_string(const char *value, char *out, size_t out_len)
{
    size_t used = 0;

    if (out == NULL || out_len < 3) {
        return "\"\"";
    }
    out[0] = '"';
    used = c300x_json_escape_string(value, out + 1, out_len - 2);
    out[used + 1] = '"';
    out[used + 2] = '\0';
    return out;
}

const char *c300x_json_string_or_null(const char *value, char *out, size_t out_len)
{
    if (value == NULL || value[0] == '\0') {
        return "null";
    }
    return c300x_json_string(value, out, out_len);
}

void c300x_json_string_field(const char *body, const char *field, char *out, size_t out_len)
{
    char pattern[64];
    const char *found;
    const char *ptr;
    size_t written = 0;

    if (out == NULL || out_len == 0) {
        return;
    }
    out[0] = '\0';
    if (body == NULL || field == NULL) {
        return;
    }
    snprintf(pattern, sizeof(pattern), "\"%s\"", field);
    found = strstr(body, pattern);
    if (found == NULL) {
        return;
    }
    ptr = strchr(found + strlen(pattern), ':');
    if (ptr == NULL) {
        return;
    }
    ptr++;
    while (*ptr != '\0' && isspace((unsigned char)*ptr)) {
        ptr++;
    }
    if (*ptr != '"') {
        return;
    }
    ptr++;
    while (*ptr != '\0' && *ptr != '"' && written + 1 < out_len) {
        if (*ptr == '\\' && ptr[1] != '\0') {
            ptr++;
        }
        out[written++] = *ptr++;
    }
    out[written] = '\0';
}

int c300x_json_bool_field(const char *body, const char *field, int *out)
{
    char pattern[64];
    const char *found;
    const char *ptr;

    if (body == NULL || field == NULL || out == NULL) {
        return 0;
    }
    snprintf(pattern, sizeof(pattern), "\"%s\"", field);
    found = strstr(body, pattern);
    if (found == NULL) {
        return 0;
    }
    ptr = strchr(found + strlen(pattern), ':');
    if (ptr == NULL) {
        return 0;
    }
    ptr++;
    while (*ptr != '\0' && isspace((unsigned char)*ptr)) {
        ptr++;
    }
    if (strncmp(ptr, "true", 4) == 0) {
        *out = 1;
        return 1;
    }
    if (strncmp(ptr, "false", 5) == 0) {
        *out = 0;
        return 1;
    }
    return 0;
}

int c300x_json_int_field(const char *body, const char *field, int *out)
{
    char pattern[64];
    const char *found;
    const char *ptr;
    char *end = NULL;
    long value;

    if (body == NULL || field == NULL || out == NULL) {
        return 0;
    }
    snprintf(pattern, sizeof(pattern), "\"%s\"", field);
    found = strstr(body, pattern);
    if (found == NULL) {
        return 0;
    }
    ptr = strchr(found + strlen(pattern), ':');
    if (ptr == NULL) {
        return 0;
    }
    ptr++;
    while (*ptr != '\0' && isspace((unsigned char)*ptr)) {
        ptr++;
    }
    errno = 0;
    value = strtol(ptr, &end, 10);
    if (errno != 0 || end == ptr) {
        return 0;
    }
    *out = (int)value;
    return 1;
}
