#ifndef C300X_AUDIO_GAIN_H
#define C300X_AUDIO_GAIN_H

#include <stddef.h>
#include <stdint.h>

/* The software gain stage for the door station's sound toward Home Assistant,
 * in whole dB. Above 0 dB a soft limiter keeps the sound linear up to
 * -6 dBFS and bends louder peaks toward full scale without ever clipping;
 * at 0 dB the sound passes unchanged. PCMU goes through a 256-entry table
 * built from the same curve, so every codec gets the same level. */
#define C300X_AUDIO_GAIN_MIN_DB (-22)
#define C300X_AUDIO_GAIN_MAX_DB 22

struct c300x_audio_gain {
    int db;
    int32_t q16;
    unsigned char pcmu[256];
};

int c300x_audio_gain_clamp_db(int db);
/* Rebuilds the table; cheap (256 samples), done only when the gain changes. */
void c300x_audio_gain_init(struct c300x_audio_gain *gain, int db);
int16_t c300x_audio_gain_sample(const struct c300x_audio_gain *gain, int16_t sample);
/* PCMU in place; an exact copy at 0 dB. */
void c300x_audio_gain_pcmu(const struct c300x_audio_gain *gain, unsigned char *data, size_t len);
/* Linear samples to PCMU with the same curve, encoded once. */
void c300x_audio_gain_linear_to_pcmu(
    const struct c300x_audio_gain *gain,
    const int16_t *samples,
    unsigned char *out,
    size_t count
);

#endif
