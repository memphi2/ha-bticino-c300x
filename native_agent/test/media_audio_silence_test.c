#define sendto capture_sendto
#include "../src/media_bridge.c"
#undef sendto

#include <assert.h>

static unsigned char sent[512];
static size_t sent_len;
static int protect_calls;
static int protect_error;

ssize_t capture_sendto(
    int fd, const void *data, size_t size, int flags,
    const struct sockaddr *address, socklen_t address_len
) {
    const struct sockaddr_in *target = (const struct sockaddr_in *)address;
    (void)flags;
    assert(fd == 42);
    assert(address_len == sizeof(*target));
    assert(target->sin_family == AF_INET);
    assert(target->sin_addr.s_addr == htonl(INADDR_LOOPBACK));
    assert(ntohs(target->sin_port) == 4000);
    assert(size <= sizeof(sent));
    memcpy(sent, data, size);
    sent_len = size;
    return (ssize_t)size;
}

static int protect(c300x_srtp_t session, void *packet, int *len) {
    assert(session != NULL);
    protect_calls++;
    if (protect_error) {
        return 1;
    }
    /* Exercise the real caller's writable SRTP authentication-tag headroom. */
    memset((unsigned char *)packet + *len, 0xc3, 10);
    *len += 10;
    return 0;
}

int main(int argc, char **argv) {
    assert(argc == 2);
    unsigned char payload_type = RTSP_BACKCHANNEL_PCMU_PAYLOAD_TYPE;
    size_t payload_len = 160;
    unsigned char silence = 0xff;
    int fd = 42;
    int port = 4000;
    bool skip = false;
    media_srtp_state_t state = {
        .audio = (c300x_srtp_t)&state,
        .available = 1,
        .audio_seq = UINT16_MAX,
        .audio_timestamp = UINT32_MAX - 79,
        .audio_ssrc = 0x12345678,
    };
    if (strcmp(argv[1], "speex_ondemand") == 0) {
        payload_type = MEDIA_AUDIO_PAYLOAD_TYPE;
        payload_len = 1;
        silence = MEDIA_AUDIO_SILENCE_PAYLOAD;
    } else if (strcmp(argv[1], "speex_ring") == 0) {
        payload_type = RING_AUDIO_PAYLOAD_TYPE;
        payload_len = 1;
        silence = MEDIA_AUDIO_SILENCE_PAYLOAD;
    } else if (strcmp(argv[1], "unavailable") == 0) {
        state.available = 0;
        skip = true;
    } else if (strcmp(argv[1], "null_state") == 0) {
        skip = true;
    } else if (strcmp(argv[1], "null_session") == 0) {
        state.audio = NULL;
        skip = true;
    } else if (strcmp(argv[1], "invalid_fd") == 0) {
        fd = -1;
        skip = true;
    } else if (strcmp(argv[1], "invalid_port") == 0) {
        port = 0;
        skip = true;
    } else if (strcmp(argv[1], "protect_failure") == 0) {
        protect_error = 1;
        skip = true;
    } else {
        assert(strcmp(argv[1], "pcmu") == 0);
    }
    g_srtp_api.initialized = 1;
    g_srtp_api.available = 1;
    g_srtp_api.srtp_protect = protect;
    send_media_audio_silence_payload_type(
        fd, port, strcmp(argv[1], "null_state") == 0 ? NULL : &state, payload_type
    );
    if (skip) {
        assert(sent_len == 0);
        assert(protect_calls == (protect_error ? 1 : 0));
        assert(state.audio_seq == UINT16_MAX);
        assert(state.audio_timestamp == UINT32_MAX - 79);
        return 0;
    }
    assert(protect_calls == 1);
    assert(sent_len == 12 + payload_len + 10);
    assert(sent[0] == 0x80 && sent[1] == payload_type);
    assert(load_be16(sent + 2) == UINT16_MAX);
    assert(load_be32(sent + 4) == UINT32_MAX - 79);
    assert(load_be32(sent + 8) == state.audio_ssrc);
    for (size_t i = 12; i < 12 + payload_len; i++) assert(sent[i] == silence);
    for (size_t i = 12 + payload_len; i < sent_len; i++) assert(sent[i] == 0xc3);
    assert(state.audio_seq == 0 && state.audio_timestamp == 80);
    send_media_audio_silence_payload_type(fd, port, &state, payload_type);
    assert(load_be16(sent + 2) == 0 && load_be32(sent + 4) == 80);
    assert(state.audio_seq == 1 && state.audio_timestamp == 240);
    return 0;
}
