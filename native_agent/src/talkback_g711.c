#include "talkback_g711.h"

#include "media_audio.h"

void c300x_talkback_g711_store(
    int16_t *frame,
    const unsigned char *input,
    size_t count,
    bool pcma,
    bool copy
)
{
    for (size_t index = 0; index < count; index++) {
        frame[index] = pcma
            ? c300x_pcma_decode(input[index])
            : copy ? input[index] : c300x_pcmu_decode(input[index]);
    }
}

void c300x_talkback_g711_pcmu(
    unsigned char *payload,
    const int16_t *frame,
    size_t count,
    bool copy
)
{
    for (size_t index = 0; index < count; index++) {
        payload[index] = copy
            ? (unsigned char)frame[index]
            : c300x_pcmu_encode(frame[index]);
    }
}
