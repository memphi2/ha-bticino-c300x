/* Production codec functions, original ARM codec library; no sockets or ALSA. */
#include "../src/media_bridge.c"

#include <assert.h>

int main(void)
{
    int16_t input[RTSP_AUDIO_FRAME_SAMPLES];
    struct {
        uint32_t before;
        int16_t samples[RTSP_AUDIO_FRAME_SAMPLES];
        uint32_t after;
    } output = { .before = 0x12345678, .after = 0x87654321 };
    unsigned char payload[512];
    size_t encoded = 0;
    int nonzero = 0;

    assert(RTSP_AUDIO_FRAME_SAMPLES == 160);
    for (int frame = 0; frame < 20; frame++) {
        for (size_t i = 0; i < RTSP_AUDIO_FRAME_SAMPLES; i++) {
            input[i] = (int16_t)((int)((i + frame * 160) % 20) * 200 - 1900);
        }
        assert(speex_encode_pcm_frame(input, payload, sizeof(payload), &encoded));
        assert(encoded > 0 && encoded < sizeof(payload));
        assert(speex_decode_audio_frame(payload, encoded, output.samples, RTSP_AUDIO_FRAME_SAMPLES));
        assert(output.before == 0x12345678 && output.after == 0x87654321);
        for (size_t i = 0; i < RTSP_AUDIO_FRAME_SAMPLES; i++) {
            nonzero += output.samples[i] != 0;
        }
    }
    assert(nonzero > 160);
    assert(!speex_decode_audio_frame(payload, encoded, output.samples, 159));
    assert(!speex_decode_audio_frame(payload, 0, output.samples, 160));
    assert(!speex_encode_pcm_frame(NULL, payload, sizeof(payload), &encoded));
    c300x_speex_api_t *api = speex_api();
    api->speex_bits_destroy(g_speex_encoder.bits.bytes);
    api->speex_encoder_destroy(g_speex_encoder.state);
    api->speex_bits_destroy(g_speex_decoder.bits.bytes);
    api->speex_decoder_destroy(g_speex_decoder.state);
    dlclose(api->handle);
    puts("speex/8000: 20 production encode/decode frames, 160 samples each");
    return 0;
}
