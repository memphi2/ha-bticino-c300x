/* Real TCP peers and ephemeral UDP listener; no vendor or device I/O. */
#include "../src/media_bridge.c"
#include <assert.h>

static void tcp_pair(int pair[2], bool mapped, bool ipv6, bool other_ip) {
    int family = mapped || ipv6 ? AF_INET6 : AF_INET;
    int listener = socket(family, SOCK_STREAM, 0);
    assert(listener >= 0);
    struct sockaddr_in v4 = {.sin_family = AF_INET};
    struct sockaddr_in6 v6 = {.sin6_family = AF_INET6};
    socklen_t size;
    if (family == AF_INET6) {
        int only = 0;
        assert(setsockopt(listener, IPPROTO_IPV6, IPV6_V6ONLY, &only, sizeof(only)) == 0);
        assert(inet_pton(AF_INET6, mapped ? "::ffff:127.0.0.1" : "::1", &v6.sin6_addr) == 1);
        assert(bind(listener, (struct sockaddr *)&v6, sizeof(v6)) == 0);
        size = sizeof(v6);
        assert(getsockname(listener, (struct sockaddr *)&v6, &size) == 0);
        v4.sin_port = v6.sin6_port;
    } else {
        assert(inet_pton(AF_INET, "127.0.0.1", &v4.sin_addr) == 1);
        assert(bind(listener, (struct sockaddr *)&v4, sizeof(v4)) == 0);
        size = sizeof(v4);
        assert(getsockname(listener, (struct sockaddr *)&v4, &size) == 0);
    }
    assert(listen(listener, 1) == 0);
    pair[0] = socket(ipv6 ? AF_INET6 : AF_INET, SOCK_STREAM, 0);
    assert(pair[0] >= 0);
    if (ipv6) {
        assert(connect(pair[0], (struct sockaddr *)&v6, sizeof(v6)) == 0);
    } else {
        struct sockaddr_in source = {.sin_family = AF_INET};
        assert(inet_pton(AF_INET, other_ip ? "127.0.0.2" : "127.0.0.1", &source.sin_addr) == 1);
        assert(bind(pair[0], (struct sockaddr *)&source, sizeof(source)) == 0);
        assert(inet_pton(AF_INET, "127.0.0.1", &v4.sin_addr) == 1);
        assert(connect(pair[0], (struct sockaddr *)&v4, sizeof(v4)) == 0);
    }
    pair[1] = accept(listener, NULL, NULL);
    assert(pair[1] >= 0);
    close(listener);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    const char *test = argv[1];
    int http[2], rtsp[2];
    tcp_pair(http, strcmp(test, "http_mapped") == 0, strcmp(test, "http_ipv6") == 0,
        strcmp(test, "other_http_ip") == 0);
    tcp_pair(rtsp, strcmp(test, "rtsp_mapped") == 0, strcmp(test, "rtsp_ipv6") == 0,
        strcmp(test, "other_rtsp_ip") == 0);
    int listener = socket(AF_INET, SOCK_DGRAM, 0);
    assert(listener >= 0);
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    if (strcmp(test, "unbound_listener") != 0) {
        assert(bind(listener, (struct sockaddr *)&address, sizeof(address)) == 0);
    }
    /* The readiness query uses opaque video identity, never video internals. */
    struct c300x_video *video = malloc(1), *other_video = malloc(1);
    assert(video != NULL && other_video != NULL);
    media_srtp_state_t state = {.audio = (void *)1};
    g_bridge.video = video;
    g_bridge.talkback_started = true;
    g_bridge.talkback_fd = listener;
    g_bridge.ring_call_active = g_bridge.ring_answered = g_bridge.ring_audio_active = true;
    g_bridge.ring_srtp_state = &state;
    g_bridge.ring_audio_rtp_fd = listener;
    g_bridge.ring_target_audio_port = 1234;
    g_bridge.rtsp_clients[0] = (rtsp_client_slot_t){.active = true, .played = true, .fd = rtsp[1]};
    const struct c300x_video *query_video = video;
    int query_fd = http[1], extra_fd = -1;
    bool expected = strcmp(test, "ready") == 0 || strcmp(test, "http_mapped") == 0
        || strcmp(test, "rtsp_mapped") == 0 || strcmp(test, "pending_data") == 0;
    if (strcmp(test, "preplay") == 0) g_bridge.rtsp_clients[0].played = false;
    if (strcmp(test, "inactive") == 0) g_bridge.rtsp_clients[0].active = false;
    if (strcmp(test, "parked") == 0) g_bridge.rtsp_clients[0].parked = true;
    if (strcmp(test, "stale") == 0) assert(shutdown(rtsp[1], SHUT_RDWR) == 0);
    if (strcmp(test, "disconnected") == 0) assert(shutdown(rtsp[0], SHUT_RDWR) == 0);
    if (strcmp(test, "stopped_listener") == 0) g_bridge.talkback_started = false;
    if (strcmp(test, "missing_listener") == 0) g_bridge.talkback_fd = -1;
    if (strcmp(test, "closed_listener") == 0) { close(listener); listener = -1; }
    if (strcmp(test, "tcp_listener") == 0) g_bridge.talkback_fd = http[1];
    if (strcmp(test, "inactive_ring") == 0) g_bridge.ring_call_active = false;
    if (strcmp(test, "unanswered") == 0) g_bridge.ring_answered = false;
    if (strcmp(test, "no_audio") == 0) g_bridge.ring_audio_active = false;
    if (strcmp(test, "ring_stopping") == 0) g_bridge.ring_call_stop = true;
    if (strcmp(test, "receiver_stopping") == 0) g_bridge.ring_stop = true;
    if (strcmp(test, "bridge_stopping") == 0) g_bridge.stop_in_progress = true;
    if (strcmp(test, "proxy_stopping") == 0) g_bridge.talkback_stop = true;
    if (strcmp(test, "proxy_joining") == 0) g_bridge.talkback_joining = true;
    if (strcmp(test, "no_srtp") == 0) g_bridge.ring_srtp_state = NULL;
    if (strcmp(test, "no_srtp_audio") == 0) state.audio = NULL;
    if (strcmp(test, "no_output") == 0) g_bridge.ring_audio_rtp_fd = -1;
    if (strcmp(test, "no_target") == 0) g_bridge.ring_target_audio_port = 0;
    if (strcmp(test, "wrong_video") == 0) query_video = other_video;
    if (strcmp(test, "null_video") == 0) query_video = NULL;
    if (strcmp(test, "invalid_peer") == 0) query_fd = -1;
    if (strcmp(test, "unconnected_peer") == 0) {
        extra_fd = socket(AF_INET, SOCK_STREAM, 0);
        assert(extra_fd >= 0);
        query_fd = extra_fd;
    }
    if (strcmp(test, "pending_data") == 0) assert(send(rtsp[0], "x", 1, 0) == 1);
    assert(c300x_media_ring_talkback_peer_ready(query_video, query_fd) == expected);
    if (strcmp(test, "pending_data") == 0) {
        char pending;
        assert(recv(rtsp[1], &pending, 1, MSG_DONTWAIT) == 1 && pending == 'x');
    }
    if (strcmp(test, "preplay") == 0) {
        g_bridge.rtsp_clients[0].played = true;
        assert(c300x_media_ring_talkback_peer_ready(video, http[1]));
        g_bridge.rtsp_clients[0].active = false;
        assert(!c300x_media_ring_talkback_peer_ready(video, http[1]));
    }
    struct sockaddr_in sender = {.sin_family = AF_INET};
    assert(inet_pton(AF_INET, "127.0.0.1", &sender.sin_addr) == 1);
    if (expected) assert(udp_talkback_peer_allowed(&g_bridge, &sender));
    assert(g_bridge.rtsp_play_requests == 0 && g_bridge.ring_last_talkback_ms == 0);
    if (listener >= 0) close(listener);
    if (extra_fd >= 0) close(extra_fd);
    close(http[0]); close(http[1]); close(rtsp[0]); close(rtsp[1]);
    free(video); free(other_video);
    return 0;
}
