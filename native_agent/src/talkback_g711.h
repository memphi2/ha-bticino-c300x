#ifndef C300X_TALKBACK_G711_H
#define C300X_TALKBACK_G711_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Talkback arrives as G.711 in packets of any size and leaves in 20 ms frames.
   With copy set, PCMU bytes for a PCMU device are kept as they are; otherwise
   the bytes are held as PCM samples for the encoder. */
void c300x_talkback_g711_store(
    int16_t *frame,
    const unsigned char *input,
    size_t count,
    bool pcma,
    bool copy
);
void c300x_talkback_g711_pcmu(
    unsigned char *payload,
    const int16_t *frame,
    size_t count,
    bool copy
);

#endif
