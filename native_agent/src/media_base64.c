#include "media_base64.h"

static int base64_value(char ch)
{
    if (ch >= 'A' && ch <= 'Z') {
        return ch - 'A';
    }
    if (ch >= 'a' && ch <= 'z') {
        return ch - 'a' + 26;
    }
    if (ch >= '0' && ch <= '9') {
        return ch - '0' + 52;
    }
    if (ch == '+') {
        return 62;
    }
    if (ch == '/') {
        return 63;
    }
    return -1;
}

bool c300x_media_base64_encode(const unsigned char *data, size_t len, char *out, size_t out_len)
{
    static const char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    size_t needed = ((len + 2) / 3) * 4;
    size_t pos = 0;

    if (out_len <= needed) {
        return false;
    }
    for (size_t index = 0; index < len; index += 3) {
        unsigned int value = ((unsigned int)data[index]) << 16;
        int remaining = (int)(len - index);
        if (remaining > 1) {
            value |= ((unsigned int)data[index + 1]) << 8;
        }
        if (remaining > 2) {
            value |= (unsigned int)data[index + 2];
        }
        out[pos++] = alphabet[(value >> 18) & 0x3f];
        out[pos++] = alphabet[(value >> 12) & 0x3f];
        out[pos++] = remaining > 1 ? alphabet[(value >> 6) & 0x3f] : '=';
        out[pos++] = remaining > 2 ? alphabet[value & 0x3f] : '=';
    }
    out[pos] = '\0';
    return true;
}

bool c300x_media_base64_decode(
    const char *text,
    unsigned char *out,
    size_t out_len,
    size_t *decoded_len
) {
    size_t pos = 0;
    int values[4];
    int count = 0;

    if (text == NULL || out == NULL || decoded_len == NULL) {
        return false;
    }
    *decoded_len = 0;
    while (*text != '\0' && *text != '\r' && *text != '\n' && *text != ';' && *text != '|') {
        if (*text == '=') {
            values[count++] = -2;
        } else {
            int value = base64_value(*text);
            if (value < 0) {
                return false;
            }
            values[count++] = value;
        }
        text++;
        if (count != 4) {
            continue;
        }
        if (values[0] < 0 || values[1] < 0 || pos >= out_len) {
            return false;
        }
        out[pos++] = (unsigned char)((values[0] << 2) | (values[1] >> 4));
        if (values[2] != -2) {
            if (values[2] < 0 || pos >= out_len) {
                return false;
            }
            out[pos++] = (unsigned char)(((values[1] & 0x0f) << 4) | (values[2] >> 2));
        }
        if (values[2] == -2 && values[3] != -2) {
            return false;
        }
        if (values[3] != -2) {
            if (values[3] < 0 || pos >= out_len) {
                return false;
            }
            out[pos++] = (unsigned char)(((values[2] & 0x03) << 6) | values[3]);
        }
        count = 0;
    }
    if (count != 0) {
        return false;
    }
    *decoded_len = pos;
    return true;
}
