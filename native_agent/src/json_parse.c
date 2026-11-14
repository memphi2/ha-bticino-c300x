#include "json_util.h"

#include <stdint.h>
#include <string.h>

static const char *skip_space(const char *p, const char *end)
{
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')) {
        p++;
    }
    return p;
}

static int hex4(const char **p, const char *end, uint32_t *value)
{
    *value = 0;
    if (end - *p < 4) {
        return 0;
    }
    for (int i = 0; i < 4; i++) {
        unsigned char ch = (unsigned char)*(*p)++;
        int digit = ch >= '0' && ch <= '9' ? ch - '0'
            : ch >= 'a' && ch <= 'f' ? ch - 'a' + 10
            : ch >= 'A' && ch <= 'F' ? ch - 'A' + 10 : -1;
        if (digit < 0) {
            return 0;
        }
        *value = (*value << 4) | (unsigned)digit;
    }
    return 1;
}

int c300x_json_decode_string(const char *p, const char *end,
    char *out, size_t capacity, const char **after)
{
    size_t used = 0;
    if (out != NULL && capacity > 0) {
        out[0] = '\0';
    }
    if (p == NULL || p >= end || *p++ != '"') {
        return 0;
    }
    while (p < end) {
        uint32_t cp = (unsigned char)*p++;
        if (cp == '"') {
            if (out != NULL) {
                if (used >= capacity) {
                    goto invalid;
                }
                out[used] = '\0';
            }
            if (after != NULL) {
                *after = p;
            }
            return 1;
        }
        if (cp < 0x20) {
            goto invalid;
        }
        if (cp == '\\') {
            if (p >= end) {
                goto invalid;
            }
            cp = (unsigned char)*p++;
            switch (cp) {
            case '"': case '\\': case '/': break;
            case 'b': cp = '\b'; break;
            case 'f': cp = '\f'; break;
            case 'n': cp = '\n'; break;
            case 'r': cp = '\r'; break;
            case 't': cp = '\t'; break;
            case 'u':
                if (!hex4(&p, end, &cp)) {
                    goto invalid;
                }
                if (cp >= 0xd800 && cp <= 0xdbff) {
                    uint32_t low;
                    if (end - p < 6 || p[0] != '\\' || p[1] != 'u') {
                        goto invalid;
                    }
                    p += 2;
                    if (!hex4(&p, end, &low) || low < 0xdc00 || low > 0xdfff) {
                        goto invalid;
                    }
                    cp = 0x10000 + ((cp - 0xd800) << 10) + low - 0xdc00;
                } else if (cp >= 0xdc00 && cp <= 0xdfff) {
                    goto invalid;
                }
                /* All consumers use C strings: embedded NUL must not alias
                 * a different credential, path or confirmation value. */
                if (cp == 0) {
                    goto invalid;
                }
                break;
            default: goto invalid;
            }
        } else if (cp >= 0x80) {
            int count;
            uint32_t minimum;
            if (cp >= 0xc2 && cp <= 0xdf) {
                cp &= 0x1f; count = 1; minimum = 0x80;
            } else if (cp >= 0xe0 && cp <= 0xef) {
                cp &= 0x0f; count = 2; minimum = 0x800;
            } else if (cp >= 0xf0 && cp <= 0xf4) {
                cp &= 0x07; count = 3; minimum = 0x10000;
            } else {
                goto invalid;
            }
            for (int i = 0; i < count; i++) {
                if (p >= end || ((unsigned char)*p & 0xc0) != 0x80) {
                    goto invalid;
                }
                cp = (cp << 6) | ((unsigned char)*p++ & 0x3f);
            }
            if (cp < minimum || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) {
                goto invalid;
            }
        }
        unsigned char bytes[4];
        size_t count;
        if (cp < 0x80) {
            bytes[0] = (unsigned char)cp; count = 1;
        } else if (cp < 0x800) {
            bytes[0] = 0xc0 | (cp >> 6);
            bytes[1] = 0x80 | (cp & 0x3f); count = 2;
        } else if (cp < 0x10000) {
            bytes[0] = 0xe0 | (cp >> 12);
            bytes[1] = 0x80 | ((cp >> 6) & 0x3f);
            bytes[2] = 0x80 | (cp & 0x3f); count = 3;
        } else {
            bytes[0] = 0xf0 | (cp >> 18);
            bytes[1] = 0x80 | ((cp >> 12) & 0x3f);
            bytes[2] = 0x80 | ((cp >> 6) & 0x3f);
            bytes[3] = 0x80 | (cp & 0x3f); count = 4;
        }
        if (out != NULL) {
            if (capacity <= used || count >= capacity - used) {
                goto invalid;
            }
            memcpy(out + used, bytes, count);
            used += count;
        }
    }
invalid:
    if (out != NULL && capacity > 0) {
        out[0] = '\0';
    }
    return 0;
}

static const char *skip_value(const char *p, const char *end, int depth)
{
    p = skip_space(p, end);
    if (p >= end || depth > 32) {
        return NULL;
    }
    if (*p == '"') {
        return c300x_json_decode_string(p, end, NULL, 0, &p) ? p : NULL;
    }
    if (*p == '{' || *p == '[') {
        int object = *p++ == '{';
        char closing = object ? '}' : ']';
        p = skip_space(p, end);
        if (p < end && *p == closing) {
            return p + 1;
        }
        for (;;) {
            if (object) {
                if (!c300x_json_decode_string(p, end, NULL, 0, &p)) {
                    return NULL;
                }
                p = skip_space(p, end);
                if (p >= end || *p++ != ':') {
                    return NULL;
                }
            }
            p = skip_value(p, end, depth + 1);
            if (p == NULL) {
                return NULL;
            }
            p = skip_space(p, end);
            if (p < end && *p == closing) {
                return p + 1;
            }
            if (p >= end || *p++ != ',') {
                return NULL;
            }
            p = skip_space(p, end);
        }
    }
    const char *literals[] = {"true", "false", "null"};
    for (size_t i = 0; i < sizeof(literals) / sizeof(literals[0]); i++) {
        size_t length = strlen(literals[i]);
        if ((size_t)(end - p) >= length && memcmp(p, literals[i], length) == 0) {
            return p + length;
        }
    }
    if (*p == '-') {
        p++;
    }
    if (p >= end || *p < '0' || *p > '9') {
        return NULL;
    }
    if (*p++ != '0') {
        while (p < end && *p >= '0' && *p <= '9') {
            p++;
        }
    }
    if (p < end && *p == '.') {
        p++;
        if (p >= end || *p < '0' || *p > '9') {
            return NULL;
        }
        while (p < end && *p >= '0' && *p <= '9') {
            p++;
        }
    }
    if (p < end && (*p == 'e' || *p == 'E')) {
        p++;
        if (p < end && (*p == '+' || *p == '-')) {
            p++;
        }
        if (p >= end || *p < '0' || *p > '9') {
            return NULL;
        }
        while (p < end && *p >= '0' && *p <= '9') {
            p++;
        }
    }
    return p;
}

const char *c300x_json_skip_value(const char *p, const char *end)
{
    return skip_value(p, end, 0);
}

int c300x_json_object_valid(const char *body)
{
    const char *end = body + strlen(body);
    const char *start = skip_space(body, end);
    if (start == end || *start != '{') {
        return 0;
    }
    const char *after = skip_value(start, end, 0);
    return after != NULL && skip_space(after, end) == end;
}

int c300x_json_find_member(const char *p, const char *end,
    const char *key, const char **value)
{
    p = skip_space(p, end);
    if (p >= end || *p++ != '{') {
        return 0;
    }
    while ((p = skip_space(p, end)) < end && *p != '}') {
        char decoded[128];
        const char *after;
        if (!c300x_json_decode_string(p, end, NULL, 0, &after)) {
            return 0;
        }
        int matches = c300x_json_decode_string(p, end, decoded, sizeof(decoded), NULL)
            && strcmp(decoded, key) == 0;
        p = skip_space(after, end);
        if (p >= end || *p++ != ':') {
            return 0;
        }
        p = skip_space(p, end);
        if (matches) {
            *value = p;
            return 1;
        }
        p = skip_value(p, end, 0);
        if (p == NULL) {
            return 0;
        }
        p = skip_space(p, end);
        if (p >= end || *p++ != ',') {
            return 0;
        }
    }
    return 0;
}
