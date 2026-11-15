#include "../src/media_bridge.c"
#include "../src/media_audio.c"

#include <assert.h>

static void send_packet(media_bridge_t *bridge, unsigned char payload_type,
                        uint16_t sequence, const unsigned char *payload, size_t size)
{
    unsigned char packet[12 + 400] = {0x80, payload_type};
    assert(size <= 400);
    packet[2] = (unsigned char)(sequence >> 8);
    packet[3] = (unsigned char)sequence;
    memcpy(packet + 12, payload, size);
    assert(forward_pcm_backchannel_packet(bridge, packet, 12 + size, 12, payload_type));
}

int main(void)
{
    static media_bridge_t bridge;
    unsigned char input[320], frame[RTSP_BACKCHANNEL_TALKBACK_PAYLOAD_MAX];
    size_t frame_len = 0;
    bool marker = false;

    assert(pthread_mutex_init(&bridge.mutex, NULL) == 0);
    bridge.device_codec_pcmu = 1;
    /* Every PCMU code, including 0x7f: decoding and encoding again would
       turn that one into 0xff. */
    for (size_t index = 0; index < sizeof(input); index++) {
        input[index] = (unsigned char)(index * 7 + 0x7f);
    }
    assert(input[0] == 0x7f);

    /* Packets of any size leave as complete 20 ms frames with the same bytes. */
    send_packet(&bridge, RTSP_BACKCHANNEL_PCMU_PAYLOAD_TYPE, 1, input, 100);
    assert(bridge.talkback_queue_len == 0);
    send_packet(&bridge, RTSP_BACKCHANNEL_PCMU_PAYLOAD_TYPE, 2, input + 100, 220);
    assert(bridge.talkback_queue_len == 2);
    for (size_t part = 0; part < 2; part++) {
        assert(pop_talkback_payload_locked(&bridge, frame, &frame_len, &marker));
        assert(frame_len == 160);
        assert(memcmp(frame, input + part * 160, 160) == 0);
    }

    /* PCMA still has to become PCMU for the device. */
    for (size_t index = 0; index < 160; index++) {
        input[index] = (unsigned char)(index + 3);
    }
    send_packet(&bridge, RTSP_BACKCHANNEL_PCMA_PAYLOAD_TYPE, 3, input, 160);
    assert(pop_talkback_payload_locked(&bridge, frame, &frame_len, &marker));
    assert(frame_len == 160);
    for (size_t index = 0; index < 160; index++) {
        assert(frame[index] == c300x_pcmu_encode(c300x_pcma_decode(input[index])));
    }
    assert(memcmp(frame, input, 160) != 0);
    return 0;
}
