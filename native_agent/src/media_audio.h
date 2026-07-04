#ifndef C300X_MEDIA_AUDIO_H
#define C300X_MEDIA_AUDIO_H

#include <stdint.h>

#define C300X_DOORSTATION_AUDIO_GAIN_MIN_TENTHS (-200)
#define C300X_DOORSTATION_AUDIO_GAIN_MAX_TENTHS 200
#define C300X_DOORSTATION_AUDIO_GAIN_STEP_TENTHS 5
#define C300X_AUDIO_GAIN_Q12_NEUTRAL 4096

int c300x_doorstation_audio_gain_normalize_tenths(int gain_tenths);
int c300x_doorstation_audio_gain_q12_for_tenths(int gain_tenths);
int c300x_audio_gain_q12_or_neutral(int gain_q12);
int16_t c300x_pcmu_decode(unsigned char value);
int16_t c300x_pcma_decode(unsigned char value);
int16_t c300x_audio_gain_apply(int16_t sample, int gain_q12);
unsigned char c300x_pcmu_encode(int16_t sample);

#endif
