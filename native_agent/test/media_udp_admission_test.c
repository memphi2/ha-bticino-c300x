/* Real TCP peer and UDP proxy dispatch; only the SRTP cipher is substituted. */
#include "../src/media_bridge.c"
#include <assert.h>

/* Keep the real proxy and socket I/O, but isolate its well-known ports from
 * other worktrees and local services. Also remap the historical raw fallback
 * so its regression detector remains effective without reserving UDP/4000. */
static in_port_t raw_sink_port;
int __real_bind(int fd, const struct sockaddr *address, socklen_t size);
ssize_t __real_sendto(int fd, const void *data, size_t len, int flags,
    const struct sockaddr *address, socklen_t size);

int __wrap_bind(int fd, const struct sockaddr *address, socklen_t size) {
    if (size == sizeof(struct sockaddr_in) && address->sa_family == AF_INET) {
        struct sockaddr_in local = *(const struct sockaddr_in *)address;
        if (ntohs(local.sin_port) == C300X_TALKBACK_RTP_PORT || ntohs(local.sin_port) == 4000) {
            local.sin_port = 0;
            local.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            return __real_bind(fd, (struct sockaddr *)&local, sizeof(local));
        }
    }
    return __real_bind(fd, address, size);
}

ssize_t __wrap_sendto(int fd, const void *data, size_t len, int flags,
    const struct sockaddr *address, socklen_t size) {
    if (size == sizeof(struct sockaddr_in) && address->sa_family == AF_INET) {
        struct sockaddr_in target = *(const struct sockaddr_in *)address;
        if (ntohs(target.sin_port) == 4000 && target.sin_addr.s_addr == htonl(INADDR_LOOPBACK)) {
            assert(raw_sink_port != 0);
            target.sin_port = raw_sink_port;
            return __real_sendto(fd, data, len, flags, (struct sockaddr *)&target, sizeof(target));
        }
    }
    return __real_sendto(fd, data, len, flags, address, size);
}

static int protect(c300x_srtp_t session, void *packet, int *len) {
    assert(session != NULL && packet != NULL && *len > 12);
    return 0;
}

static int bound_socket(int type, const char *ip, int port, struct sockaddr_in *addr) {
    int fd = socket(AF_INET, type, 0);
    assert(fd >= 0);
    *addr = (struct sockaddr_in){.sin_family = AF_INET, .sin_port = htons(port)};
    assert(inet_pton(AF_INET, ip, &addr->sin_addr) == 1);
    assert(bind(fd, (struct sockaddr *)addr, sizeof(*addr)) == 0);
    socklen_t size = sizeof(*addr);
    assert(getsockname(fd, (struct sockaddr *)addr, &size) == 0);
    return fd;
}

int main(int argc, char **argv) {
    assert(argc == 3);
    const char *mode = argv[1], *test = argv[2];
    bool pcmu = strcmp(test, "pcmu") == 0;
    bool allowed = strcmp(test, "authorized") == 0 || pcmu || strcmp(test, "csrc") == 0;
    media_bridge_t bridge = {.mutex = PTHREAD_MUTEX_INITIALIZER, .talkback_fd = -1};
    media_srtp_state_t state = {.audio = (void *)1, .audio_ssrc = 42};
    struct sockaddr_in listen_addr, sink_addr, raw_addr, sender_addr;
    int listener = bound_socket(SOCK_STREAM, "127.0.0.1", 0, &listen_addr);
    assert(listen(listener, 1) == 0);
    int client = socket(AF_INET, SOCK_STREAM, 0);
    assert(client >= 0);
    assert(connect(client, (struct sockaddr *)&listen_addr, sizeof(listen_addr)) == 0);
    int peer = accept(listener, NULL, NULL);
    assert(peer >= 0);
    close(listener);
    int sink = bound_socket(SOCK_DGRAM, "127.0.0.1", 0, &sink_addr);
    /* Detect the former unprotected fallback as well as protected dispatch. */
    int raw = bound_socket(SOCK_DGRAM, "127.0.0.1", 4000, &raw_addr);
    raw_sink_port = raw_addr.sin_port;
    int sender = bound_socket(SOCK_DGRAM,
        strcmp(test, "untrusted") == 0 ? "127.0.0.2" : "127.0.0.1", 0, &sender_addr);
    int output = socket(AF_INET, SOCK_DGRAM, 0);
    assert(output >= 0);
    struct sockaddr_in legacy_target = raw_addr;
    legacy_target.sin_port = htons(4000);
    assert(sendto(output, "x", 1, 0, (struct sockaddr *)&legacy_target, sizeof(legacy_target)) == 1);
    unsigned char observed;
    assert(recv(raw, &observed, 1, 0) == 1 && observed == 'x');
    bridge.rtsp_clients[0] = (rtsp_client_slot_t){.active = true, .played = true, .fd = peer};
    bridge.device_codec_pcmu = pcmu;
    if (strcmp(mode, "ring") == 0) {
        bridge.ring_call_active = bridge.ring_answered = bridge.ring_audio_active = true;
        bridge.ring_srtp_state = &state;
        bridge.ring_audio_rtp_fd = output;
        bridge.ring_target_audio_port = ntohs(sink_addr.sin_port);
    } else if (strcmp(mode, "home") == 0) {
        bridge.home_call_active = bridge.home_call_answered = true;
        bridge.home_call_srtp_state = &state;
        bridge.home_call_audio_rtp_fd = output;
        bridge.home_call_target_audio_port = ntohs(sink_addr.sin_port);
    } else {
        assert(strcmp(mode, "ondemand") == 0);
        bridge.media_active = true;
        bridge.ondemand_srtp_state = &state;
        bridge.ondemand_audio_rtp_fd = output;
        bridge.ondemand_target_audio_port = ntohs(sink_addr.sin_port);
    }
    if (strcmp(test, "idle") == 0) {
        bridge.ring_call_active = bridge.home_call_active = bridge.media_active = false;
    } else if (strcmp(test, "empty") == 0 || strcmp(test, "unregistered") == 0) {
        bridge.rtsp_clients[0].active = false;
    } else if (strcmp(test, "before_play") == 0) {
        bridge.rtsp_clients[0].played = false;
    } else if (strcmp(test, "parked") == 0) {
        bridge.rtsp_clients[0].parked = true;
    } else if (strcmp(test, "stopping") == 0) {
        bridge.stop_in_progress = true;
    } else if (strcmp(test, "unanswered") == 0) {
        bridge.ring_answered = bridge.home_call_answered = false;
        bridge.ondemand_srtp_state = NULL;
    } else if (strcmp(test, "session_stopped") == 0) {
        bridge.ring_call_stop = bridge.home_call_stop = bridge.ondemand_media_stop = true;
    } else if (strcmp(test, "stale") == 0) {
        assert(shutdown(peer, SHUT_RDWR) == 0);
    } else if (strcmp(test, "disconnected") == 0) {
        assert(shutdown(client, SHUT_RDWR) == 0);
    }
    unsigned char packet[2048] = {0x80, pcmu ? 0 : 97};
    size_t length = 13;
    packet[12] = 0x55;
    if (strcmp(test, "zero") == 0) length = 0;
    if (strcmp(test, "short") == 0) length = 11;
    if (strcmp(test, "header_only") == 0) length = 12;
    if (strcmp(test, "version") == 0) packet[0] = 0x40;
    if (strcmp(test, "extension") == 0) packet[0] = 0x90;
    if (strcmp(test, "csrc_short") == 0) packet[0] = 0x8f;
    if (strcmp(test, "oversize") == 0) length = sizeof(packet);
    if (strcmp(test, "csrc") == 0) {
        packet[0] = 0x81;
        packet[16] = 0x55;
        length = 17;
    }
    g_srtp_api.initialized = g_srtp_api.available = 1;
    g_srtp_api.srtp_protect = protect;
    pthread_t worker;
    assert(pthread_create(&worker, NULL, talkback_proxy_thread, &bridge) == 0);
    bool ready = false;
    for (int i = 0; i < 500 && !ready; i++) {
        pthread_mutex_lock(&bridge.mutex);
        ready = bridge.talkback_fd >= 0;
        pthread_mutex_unlock(&bridge.mutex);
        if (!ready) usleep(2000);
    }
    assert(ready);
    struct sockaddr_in target;
    socklen_t target_size = sizeof(target);
    assert(getsockname(bridge.talkback_fd, (struct sockaddr *)&target, &target_size) == 0);
    assert(sendto(sender, packet, length, 0, (struct sockaddr *)&target, sizeof(target)) == (ssize_t)length);
    fd_set fds;
    FD_ZERO(&fds);
    FD_SET(sink, &fds);
    FD_SET(raw, &fds);
    struct timeval timeout = {0, 150000};
    int received = select((sink > raw ? sink : raw) + 1, &fds, NULL, NULL, &timeout);
    assert(received >= 0 && !FD_ISSET(raw, &fds));
    assert((received == 1) == allowed);
    if (allowed) {
        unsigned char result[2048];
        assert(recv(sink, result, sizeof(result), 0) == 13);
        assert(result[0] == 0x80 && result[12] == 0x55);
        assert(result[1] == (pcmu ? 0 : strcmp(mode, "ring") == 0 ? RING_AUDIO_PAYLOAD_TYPE : MEDIA_AUDIO_PAYLOAD_TYPE));
        assert(load_be32(result + 8) == 42);
    }
    pthread_mutex_lock(&bridge.mutex);
    bridge.talkback_stop = true;
    pthread_mutex_unlock(&bridge.mutex);
    assert(pthread_join(worker, NULL) == 0);
    close(peer); close(client); close(sink); close(raw); close(sender); close(output);
    pthread_mutex_destroy(&bridge.mutex);
    return 0;
}
