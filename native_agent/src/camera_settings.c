#include "camera_settings.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SECTION "[Answering Machine]"

static const char *const KEYS[2][4] = {
    {"BitrateRtpH", "FpsRtpH", "Width", "Height"},
    {"BitrateRtpL", "FpsRtpL", "WidthLow", "HeightLow"},
};

/* Where the digits of the single line of key in the section start and end;
 * NULL for a missing or repeated key or a value not of 1-5 digits. */
static const char *find_value(const char *data, const char *key, const char **end)
{
    const char *line = data, *found = NULL;
    size_t key_len = strlen(key);
    int inside = 0, count = 0;

    while (*line != '\0') {
        const char *next = strchr(line, '\n');
        size_t len = next != NULL ? (size_t)(next - line) : strlen(line);

        len -= len > 0 && line[len - 1] == '\r';
        if (line[0] == '[') {
            inside = len == strlen(SECTION) && strncmp(line, SECTION, len) == 0;
        } else if (inside && len > key_len && strncmp(line, key, key_len) == 0 && line[key_len] == '=') {
            const char *digits = line + key_len + 1, *stop = digits;
            while (stop < line + len && *stop >= '0' && *stop <= '9') stop++;
            if (stop != line + len || stop == digits || stop - digits > 5) {
                return NULL;
            }
            found = digits;
            *end = stop;
            count++;
        }
        if (next == NULL) break;
        line = next + 1;
    }
    return count == 1 ? found : NULL;
}

int c300x_camera_settings_parse(const char *data, int low, struct c300x_camera_values *values)
{
    int *fields[] = {&values->bitrate_kbps, &values->fps, &values->width, &values->height};
    const char *end;

    for (int i = 0; i < 4; i++) {
        const char *digits = find_value(data, KEYS[low != 0][i], &end);
        if (digits == NULL) {
            return 0;
        }
        *fields[i] = atoi(digits);
    }
    return 1;
}

/* data, freed, with the digits of key replaced; NULL when that fails. */
static char *with_value(char *data, const char *key, int value)
{
    const char *end = NULL, *digits = find_value(data, key, &end);
    size_t before, size;
    char number[12];
    char *out;

    if (digits == NULL) {
        free(data);
        return NULL;
    }
    before = (size_t)(digits - data);
    snprintf(number, sizeof(number), "%d", value);
    size = before + strlen(number) + strlen(end) + 1;
    out = malloc(size);
    if (out != NULL) {
        memcpy(out, data, before);
        snprintf(out + before, size - before, "%s%s", number, end);
    }
    free(data);
    return out;
}

char *c300x_camera_settings_with(char *data, int low, const struct c300x_camera_values *values)
{
    const int fields[] = {values->bitrate_kbps, values->fps, values->width, values->height};

    for (int i = 0; i < 4 && data != NULL; i++) {
        data = with_value(data, KEYS[low != 0][i], fields[i]);
    }
    return data;
}
