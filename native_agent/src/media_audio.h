#ifndef C300X_MEDIA_AUDIO_H
#define C300X_MEDIA_AUDIO_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

bool c300x_rtp_payload_offset(
    const unsigned char *packet,
    int packet_len,
    size_t *payload_offset
);
int16_t c300x_pcmu_decode(unsigned char value);
int16_t c300x_pcma_decode(unsigned char value);
unsigned char c300x_pcmu_encode(int16_t sample);

#endif
