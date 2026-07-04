#include "media_audio.h"

#include <stddef.h>

int c300x_doorstation_audio_gain_normalize_tenths(int gain_tenths)
{
    int offset;
    int remainder;

    if (gain_tenths < C300X_DOORSTATION_AUDIO_GAIN_MIN_TENTHS) {
        gain_tenths = C300X_DOORSTATION_AUDIO_GAIN_MIN_TENTHS;
    } else if (gain_tenths > C300X_DOORSTATION_AUDIO_GAIN_MAX_TENTHS) {
        gain_tenths = C300X_DOORSTATION_AUDIO_GAIN_MAX_TENTHS;
    }
    offset = gain_tenths - C300X_DOORSTATION_AUDIO_GAIN_MIN_TENTHS;
    remainder = offset % C300X_DOORSTATION_AUDIO_GAIN_STEP_TENTHS;
    if (remainder >= 3) {
        offset += C300X_DOORSTATION_AUDIO_GAIN_STEP_TENTHS - remainder;
    } else {
        offset -= remainder;
    }
    return C300X_DOORSTATION_AUDIO_GAIN_MIN_TENTHS + offset;
}

int c300x_doorstation_audio_gain_q12_for_tenths(int gain_tenths)
{
    static const int gain_q12[] = {
        410, 434, 460, 487, 516, 546, 579, 613, 649, 688,
        728, 772, 817, 866, 917, 971, 1029, 1090, 1154, 1223,
        1295, 1372, 1453, 1539, 1631, 1727, 1830, 1938, 2053, 2175,
        2303, 2440, 2584, 2738, 2900, 3072, 3254, 3446, 3651, 3867,
        4096, 4339, 4596, 4868, 5157, 5462, 5786, 6129, 6492, 6876,
        7284, 7715, 8173, 8657, 9170, 9713, 10289, 10898, 11544, 12228,
        12953, 13720, 14533, 15394, 16306, 17273, 18296, 19380, 20529, 21745,
        23034, 24398, 25844, 27375, 28997, 30716, 32536, 34464, 36506, 38669,
        40960
    };
    int normalized = c300x_doorstation_audio_gain_normalize_tenths(gain_tenths);
    int index = (normalized - C300X_DOORSTATION_AUDIO_GAIN_MIN_TENTHS)
        / C300X_DOORSTATION_AUDIO_GAIN_STEP_TENTHS;

    if (index < 0) {
        return gain_q12[0];
    }
    if ((size_t)index >= sizeof(gain_q12) / sizeof(gain_q12[0])) {
        return gain_q12[(sizeof(gain_q12) / sizeof(gain_q12[0])) - 1];
    }
    return gain_q12[index];
}

int c300x_audio_gain_q12_or_neutral(int gain_q12)
{
    return gain_q12 > 0 ? gain_q12 : C300X_AUDIO_GAIN_Q12_NEUTRAL;
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

int16_t c300x_audio_gain_apply(int16_t sample, int gain_q12)
{
    long scaled;

    if (gain_q12 == C300X_AUDIO_GAIN_Q12_NEUTRAL) {
        return sample;
    }
    scaled = (long)sample * gain_q12;
    if (scaled >= 0) {
        scaled = (scaled + (C300X_AUDIO_GAIN_Q12_NEUTRAL / 2))
            / C300X_AUDIO_GAIN_Q12_NEUTRAL;
    } else {
        scaled = (scaled - (C300X_AUDIO_GAIN_Q12_NEUTRAL / 2))
            / C300X_AUDIO_GAIN_Q12_NEUTRAL;
    }
    if (scaled > INT16_MAX) {
        return INT16_MAX;
    }
    if (scaled < INT16_MIN) {
        return INT16_MIN;
    }
    return (int16_t)scaled;
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
