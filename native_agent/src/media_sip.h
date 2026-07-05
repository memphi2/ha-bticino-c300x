#ifndef C300X_MEDIA_SIP_H
#define C300X_MEDIA_SIP_H

#include <stdbool.h>
#include <stddef.h>

#define C300X_MEDIA_SRTP_MASTER_KEY_LEN 30

void c300x_media_sip_header_value(
    const char *message,
    const char *name,
    char *out,
    size_t out_len
);
void c300x_media_sip_uri_from_header(const char *header, char *out, size_t out_len);
void c300x_media_sip_make_tagged_to(
    const char *to_header,
    const char *tag,
    char *out,
    size_t out_len
);
int c300x_media_sip_content_length(const char *message);
int c300x_media_sip_parse_sdp_media_port(
    const char *message,
    const char *media,
    int fallback
);
bool c300x_media_sip_parse_sdp_sdes_key(
    const char *message,
    const char *media,
    unsigned char *out,
    size_t out_len
);
int c300x_media_sip_status_code(const char *message);
void c300x_media_sip_cseq_method_value(
    const char *message,
    char *out,
    size_t out_len
);

#endif
