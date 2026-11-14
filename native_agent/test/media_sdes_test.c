#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../src/media_sip.h"
#include "../src/media_base64.h"

int main(void)
{
    unsigned char gcm[44], aes[30], out[30];
    char b64g[80], b64a[80], offer[512];
    memset(gcm, 0x11, sizeof(gcm)); memset(aes, 0x22, sizeof(aes));
    c300x_media_base64_encode(gcm, sizeof(gcm), b64g, sizeof(b64g));
    c300x_media_base64_encode(aes, sizeof(aes), b64a, sizeof(b64a));
    snprintf(offer, sizeof(offer), "v=0\r\nm=audio 7078 RTP/SAVP 98\r\na=crypto:1 AEAD_AES_256_GCM inline:%s\r\na=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:%s\r\n", b64g, b64a);
    assert(c300x_media_sip_parse_sdp_sdes_key(offer, "\r\nm=audio ", out, sizeof(out)));
    assert(memcmp(out, aes, sizeof(aes)) == 0);
    snprintf(offer, sizeof(offer), "v=0\r\nm=audio 7078 RTP/SAVP 98\r\na=crypto:1 AES_CM_128_HMAC_SHA1_80\r\ninline:%s\r\n", b64a);
    assert(!c300x_media_sip_parse_sdp_sdes_key(offer, "\r\nm=audio ", out, sizeof(out)));
    snprintf(offer, sizeof(offer), "v=0\r\nm=audio 7078 RTP/SAVP 98\r\na=crypto:1 NOT_AES_CM_128_HMAC_SHA1_80 inline:%s\r\n", b64a);
    assert(!c300x_media_sip_parse_sdp_sdes_key(offer, "\r\nm=audio ", out, sizeof(out)));
    return 0;
}
