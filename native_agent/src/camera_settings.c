#include "camera_settings.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SECTION "[Answering Machine]"
#define BITRATE_KEY "BitrateRtpH"
#define FPS_KEY "FpsRtpH"

/* The single line of key in the section: where its digits start and end.
 * NULL when the key is missing, appears more than once in any such section,
 * or has anything but up to five digits as its value. */
static const char *find_value(const char *data, const char *key, const char **end)
{
    const char *line = data, *found = NULL;
    size_t key_len = strlen(key);
    int inside = 0, count = 0;

    while (*line != '\0') {
        const char *next = strchr(line, '\n');
        size_t len = next != NULL ? (size_t)(next - line) : strlen(line);

        if (len > 0 && line[len - 1] == '\r') {
            len--;
        }
        if (line[0] == '[') {
            inside = len == strlen(SECTION) && strncmp(line, SECTION, len) == 0;
        } else if (inside && len > key_len && strncmp(line, key, key_len) == 0 && line[key_len] == '=') {
            const char *digits = line + key_len + 1, *stop = digits;
            while (stop < line + len && *stop >= '0' && *stop <= '9') {
                stop++;
            }
            if (stop != line + len || stop == digits || stop - digits > 5) {
                return NULL;
            }
            found = digits;
            *end = stop;
            count++;
        }
        if (next == NULL) {
            break;
        }
        line = next + 1;
    }
    return count == 1 ? found : NULL;
}

int c300x_camera_settings_parse(const char *data, int *bitrate, int *fps)
{
    const char *bitrate_at, *fps_at, *end;

    if ((bitrate_at = find_value(data, BITRATE_KEY, &end)) == NULL
        || (fps_at = find_value(data, FPS_KEY, &end)) == NULL) {
        return 0;
    }
    *bitrate = atoi(bitrate_at);
    *fps = atoi(fps_at);
    return 1;
}

/* data with the digits of key replaced by value; NULL when it does not fit. */
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

char *c300x_camera_settings_with(char *data, int bitrate_kbps, int fps)
{
    data = with_value(data, BITRATE_KEY, bitrate_kbps);
    return data != NULL ? with_value(data, FPS_KEY, fps) : NULL;
}
