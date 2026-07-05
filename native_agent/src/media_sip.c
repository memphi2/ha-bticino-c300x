#include "media_sip.h"

#include "media_base64.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

static void secure_zero(void *ptr, size_t len)
{
    volatile unsigned char *p = ptr;

    while (len > 0) {
        *p++ = 0;
        len--;
    }
}

void c300x_media_sip_header_value(
    const char *message,
    const char *name,
    char *out,
    size_t out_len
)
{
    size_t name_len;
    const char *line;

    if (out == NULL || out_len == 0) {
        return;
    }
    out[0] = '\0';
    if (message == NULL || name == NULL) {
        return;
    }
    name_len = strlen(name);
    line = message;
    while (line != NULL && *line != '\0') {
        const char *line_end = strstr(line, "\r\n");
        if (line_end == NULL) {
            line_end = line + strlen(line);
        }
        if (strncasecmp(line, name, name_len) == 0) {
            const char *value = line + name_len;
            size_t len;

            while (*value == ' ' || *value == '\t') {
                value++;
            }
            len = (size_t)(line_end - value);
            if (len >= out_len) {
                len = out_len - 1;
            }
            memcpy(out, value, len);
            out[len] = '\0';
            return;
        }
        if (*line_end == '\0') {
            break;
        }
        line = line_end + 2;
    }
}

void c300x_media_sip_uri_from_header(const char *header, char *out, size_t out_len)
{
    const char *start;
    const char *end = NULL;
    size_t len;

    if (out == NULL || out_len == 0) {
        return;
    }
    out[0] = '\0';
    if (header == NULL || header[0] == '\0') {
        return;
    }

    start = strchr(header, '<');
    if (start != NULL) {
        start++;
        end = strchr(start, '>');
    } else {
        start = header;
        while (*start == ' ' || *start == '\t') {
            start++;
        }
        end = start;
        while (*end != '\0' && *end != ',' && *end != '\r' && *end != '\n') {
            end++;
        }
    }

    if (start == NULL || end == NULL || end <= start) {
        return;
    }
    len = (size_t)(end - start);
    if (len >= out_len) {
        len = out_len - 1;
    }
    memcpy(out, start, len);
    out[len] = '\0';
}

void c300x_media_sip_make_tagged_to(
    const char *to_header,
    const char *tag,
    char *out,
    size_t out_len
)
{
    char uri[512];

    if (out == NULL || out_len == 0) {
        return;
    }
    c300x_media_sip_uri_from_header(to_header, uri, sizeof(uri));
    if (uri[0] != '\0') {
        snprintf(out, out_len, "<%s>;tag=%s", uri, tag);
        return;
    }
    snprintf(out, out_len, "%s;tag=%s", to_header, tag);
}

int c300x_media_sip_content_length(const char *message)
{
    char value[32];

    c300x_media_sip_header_value(message, "Content-Length:", value, sizeof(value));
    return value[0] ? atoi(value) : 0;
}

int c300x_media_sip_parse_sdp_media_port(
    const char *message,
    const char *media,
    int fallback
)
{
    const char *pos;

    if (message == NULL || media == NULL) {
        return fallback;
    }
    pos = strstr(message, media);
    if (pos == NULL) {
        return fallback;
    }
    return atoi(pos + strlen(media));
}

bool c300x_media_sip_parse_sdp_sdes_key(
    const char *message,
    const char *media,
    unsigned char *out,
    size_t out_len
)
{
    const char *section;
    const char *section_end;
    const char *line;
    unsigned char decoded[64];
    size_t decoded_len = 0;

    if (
        message == NULL
        || media == NULL
        || out == NULL
        || out_len != C300X_MEDIA_SRTP_MASTER_KEY_LEN
    ) {
        return false;
    }
    section = strstr(message, media);
    if (section == NULL) {
        return false;
    }
    section_end = strstr(section + strlen(media), "\r\nm=");
    line = section;
    while (line != NULL && *line != '\0' && (section_end == NULL || line < section_end)) {
        const char *line_end = strstr(line, "\r\n");
        if (line_end == NULL) {
            line_end = line + strlen(line);
        }
        if (
            strncasecmp(line, "a=crypto:", strlen("a=crypto:")) == 0
            && strstr(line, "AES_CM_128_HMAC_SHA1_80") != NULL
        ) {
            const char *inline_key = strstr(line, "inline:");
            if (inline_key == NULL || inline_key >= line_end) {
                return false;
            }
            inline_key += strlen("inline:");
            if (!c300x_media_base64_decode(inline_key, decoded, sizeof(decoded), &decoded_len)) {
                return false;
            }
            if (decoded_len < C300X_MEDIA_SRTP_MASTER_KEY_LEN) {
                return false;
            }
            memcpy(out, decoded, C300X_MEDIA_SRTP_MASTER_KEY_LEN);
            secure_zero(decoded, sizeof(decoded));
            return true;
        }
        if (*line_end == '\0') {
            break;
        }
        line = line_end + 2;
    }
    secure_zero(decoded, sizeof(decoded));
    return false;
}

int c300x_media_sip_status_code(const char *message)
{
    int status = 0;

    if (message == NULL || sscanf(message, "SIP/2.0 %d", &status) != 1) {
        return 0;
    }
    return status;
}

void c300x_media_sip_cseq_method_value(
    const char *message,
    char *out,
    size_t out_len
)
{
    char cseq[64];
    char *space;
    const char *method;
    size_t len;

    if (out == NULL || out_len == 0) {
        return;
    }
    c300x_media_sip_header_value(message, "CSeq:", cseq, sizeof(cseq));
    out[0] = '\0';
    space = strrchr(cseq, ' ');
    method = space != NULL ? space + 1 : cseq;
    while (*method == ' ' || *method == '\t') {
        method++;
    }
    len = strlen(method);
    while (
        len > 0
        && (
            method[len - 1] == ' '
            || method[len - 1] == '\t'
            || method[len - 1] == '\r'
            || method[len - 1] == '\n'
        )
    ) {
        len--;
    }
    if (len >= out_len) {
        len = out_len - 1;
    }
    memcpy(out, method, len);
    out[len] = '\0';
}
