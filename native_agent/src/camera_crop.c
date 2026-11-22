#include "camera_crop.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *const TAGS[4] = {"left", "top", "width", "height"};

/* The only place of needle in [from, to); NULL for none or more than one. */
static const char *find_once(const char *from, const char *to, const char *needle)
{
    size_t len = strlen(needle);
    const char *found = NULL;

    for (const char *at = from; at + len <= to; at++) {
        if (memcmp(at, needle, len) == 0) {
            if (found != NULL) {
                return NULL;
            }
            found = at;
        }
    }
    return found;
}

/* Where the digits of tag inside the crop block start and end. */
static const char *find_number(const char *data, int tag, const char **end)
{
    char open[16], close[16];
    const char *block = find_once(data, data + strlen(data), "<crop>");
    const char *block_end = block != NULL ? find_once(block, data + strlen(data), "</crop>") : NULL;
    const char *digits, *stop;

    if (block_end == NULL) {
        return NULL;
    }
    snprintf(open, sizeof(open), "<%s>", TAGS[tag]);
    snprintf(close, sizeof(close), "</%s>", TAGS[tag]);
    digits = find_once(block, block_end, open);
    if (digits == NULL) {
        return NULL;
    }
    digits += strlen(open);
    for (stop = digits; stop < block_end && *stop >= '0' && *stop <= '9'; stop++) {
    }
    if (stop == digits || stop - digits > 4 || strncmp(stop, close, strlen(close)) != 0) {
        return NULL;
    }
    *end = stop;
    return digits;
}

int c300x_camera_crop_parse(const char *data, int crop[4])
{
    const char *end;

    for (int i = 0; i < 4; i++) {
        const char *digits = find_number(data, i, &end);
        if (digits == NULL) {
            return 0;
        }
        crop[i] = atoi(digits);
    }
    return 1;
}

char *c300x_camera_crop_with(char *data, const int crop[4])
{
    for (int i = 0; i < 4 && data != NULL; i++) {
        const char *end = NULL, *digits = find_number(data, i, &end);
        char number[12], *out;
        size_t before, size;

        if (digits == NULL) {
            free(data);
            return NULL;
        }
        before = (size_t)(digits - data);
        snprintf(number, sizeof(number), "%d", crop[i]);
        size = before + strlen(number) + strlen(end) + 1;
        out = malloc(size);
        if (out != NULL) {
            memcpy(out, data, before);
            snprintf(out + before, size - before, "%s%s", number, end);
        }
        free(data);
        data = out;
    }
    return data;
}
