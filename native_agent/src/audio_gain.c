#include "audio_gain.h"

#include "media_audio.h"

#define GAIN_Q16_ONE 65536
#define LIMIT_KNEE 16384
#define LIMIT_CEILING 32635

/* 10^(dB/20) in Q16 for -22..+22 dB. */
static const int32_t gain_q16[] = {
    5206, 5841, 6554, 7353, 8250, 9257, 10387, 11654, 13076,
    14672, 16462, 18471, 20724, 23253, 26090, 29274, 32846, 36854,
    41350, 46396, 52057, 58409, 65536, 73533, 82505, 92572, 103868,
    116541, 130762, 146717, 164619, 184706, 207243, 232531, 260904, 292739,
    328458, 368536, 413504, 463959, 520571, 584090, 655360, 735326, 825049,
};

int c300x_audio_gain_clamp_db(int db)
{
    if (db < C300X_AUDIO_GAIN_MIN_DB) {
        return C300X_AUDIO_GAIN_MIN_DB;
    }
    return db > C300X_AUDIO_GAIN_MAX_DB ? C300X_AUDIO_GAIN_MAX_DB : db;
}

/* Linear below the knee; above it the rest of the headroom fills
 * asymptotically: slope 1 at the knee, never past the PCMU ceiling. A gain
 * never makes a sample quieter: where the bend would fall below the input,
 * the input passes as it is, so the curve joins 0 dB without a step. */
static int32_t soft_limit(int64_t value, int16_t input)
{
    int64_t magnitude = value < 0 ? -value : value;
    int64_t floor = input < 0 ? -(int64_t)input : input;
    int64_t room = LIMIT_CEILING - LIMIT_KNEE;
    int64_t over;

    if (magnitude <= LIMIT_KNEE) {
        return (int32_t)value;
    }
    over = magnitude - LIMIT_KNEE;
    magnitude = LIMIT_KNEE + (room * over) / (over + room);
    if (magnitude < floor) {
        magnitude = floor;
    }
    return (int32_t)(value < 0 ? -magnitude : magnitude);
}

int16_t c300x_audio_gain_sample(const struct c300x_audio_gain *gain, int16_t sample)
{
    int64_t scaled;

    if (gain->q16 == GAIN_Q16_ONE) {
        return sample;
    }
    scaled = (int64_t)sample * gain->q16;
    scaled = scaled >= 0 ? (scaled + GAIN_Q16_ONE / 2) / GAIN_Q16_ONE : -((-scaled + GAIN_Q16_ONE / 2) / GAIN_Q16_ONE);
    if (gain->q16 < GAIN_Q16_ONE) {
        return (int16_t)scaled;
    }
    return (int16_t)soft_limit(scaled, sample);
}

void c300x_audio_gain_init(struct c300x_audio_gain *gain, int db)
{
    gain->db = c300x_audio_gain_clamp_db(db);
    gain->q16 = gain_q16[gain->db - C300X_AUDIO_GAIN_MIN_DB];
    for (int code = 0; code < 256; code++) {
        gain->pcmu[code] = gain->q16 == GAIN_Q16_ONE
            ? (unsigned char)code
            : c300x_pcmu_encode(c300x_audio_gain_sample(gain, c300x_pcmu_decode((unsigned char)code)));
    }
}

void c300x_audio_gain_pcmu(const struct c300x_audio_gain *gain, unsigned char *data, size_t len)
{
    if (gain->q16 == GAIN_Q16_ONE) {
        return;
    }
    for (size_t index = 0; index < len; index++) {
        data[index] = gain->pcmu[data[index]];
    }
}

void c300x_audio_gain_linear_to_pcmu(
    const struct c300x_audio_gain *gain,
    const int16_t *samples,
    unsigned char *out,
    size_t count
)
{
    for (size_t index = 0; index < count; index++) {
        out[index] = c300x_pcmu_encode(c300x_audio_gain_sample(gain, samples[index]));
    }
}
