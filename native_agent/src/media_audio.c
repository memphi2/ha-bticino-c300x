#include "media_audio.h"

#include <stddef.h>

bool c300x_rtp_payload_offset(
    const unsigned char *packet,
    int packet_len,
    size_t *payload_offset
)
{
    size_t header_len;

    if (
        packet == NULL
        || payload_offset == NULL
        || packet_len < 12
        || (packet[0] & 0xc0) != 0x80
    ) {
        return false;
    }
    header_len = 12 + ((size_t)(packet[0] & 0x0f) * 4);
    if ((size_t)packet_len < header_len) {
        return false;
    }
    if ((packet[0] & 0x10) != 0) {
        uint16_t extension_words;
        if ((size_t)packet_len < header_len + 4) {
            return false;
        }
        extension_words = (uint16_t)(
            ((uint16_t)packet[header_len + 2] << 8) | packet[header_len + 3]
        );
        header_len += 4 + ((size_t)extension_words * 4);
        if ((size_t)packet_len < header_len) {
            return false;
        }
    }
    *payload_offset = header_len;
    return true;
}

int16_t c300x_pcmu_decode(unsigned char value)
{
    const int bias = 0x84;
    int magnitude;

    value = (unsigned char)~value;
    magnitude = ((value & 0x0f) << 3) + bias;
    magnitude <<= (value & 0x70) >> 4;
    return (int16_t)((value & 0x80) ? (bias - magnitude) : (magnitude - bias));
}

int16_t c300x_pcma_decode(unsigned char value)
{
    int exponent;
    int mantissa;
    int sample;

    value ^= 0x55;
    exponent = (value & 0x70) >> 4;
    mantissa = value & 0x0f;
    sample = mantissa << 4;
    if (exponent == 0) {
        sample += 8;
    } else {
        sample += 0x108;
        sample <<= exponent - 1;
    }
    return (int16_t)((value & 0x80) ? sample : -sample);
}

unsigned char c300x_pcmu_encode(int16_t sample)
{
    const int bias = 0x84;
    const int clip = 32635;
    int sign = 0;
    int magnitude = sample;
    int exponent = 7;
    int exponent_mask = 0x4000;
    int mantissa;
    unsigned char value;

    if (magnitude < 0) {
        sign = 0x80;
        magnitude = -magnitude;
    }
    if (magnitude > clip) {
        magnitude = clip;
    }
    magnitude += bias;
    while (exponent > 0 && (magnitude & exponent_mask) == 0) {
        exponent--;
        exponent_mask >>= 1;
    }
    mantissa = (magnitude >> (exponent + 3)) & 0x0f;
    value = (unsigned char)(sign | (exponent << 4) | mantissa);
    return (unsigned char)~value;
}
