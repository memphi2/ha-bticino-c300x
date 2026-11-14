/* Complete a synthetic SIP handshake only after a concurrent stop request. */
#include <assert.h>
#include <stdatomic.h>
#include <sys/socket.h>
static int test_connect(int, const struct sockaddr *, socklen_t);
static int test_bind(int, const struct sockaddr *, socklen_t);
#define connect test_connect
#define bind test_bind
#undef _POSIX_C_SOURCE
#include "../src/media_bridge.c"
#undef connect
#undef bind

static atomic_bool connecting, release_connect;
static int peer = -1;
static bool start_result;
static int session_attempts, session_frees, fail_session;
static int fake_create(c300x_srtp_t *session, const c300x_srtp_policy_t *policy) {
    (void)policy;
    if (++session_attempts == fail_session) return 1;
    *session = malloc(1);
    assert(*session);
    return 0;
}
static int fake_dealloc(c300x_srtp_t session) {
    free(session);
    session_frees++;
    return 0;
}
static void fake_policy(c300x_srtp_crypto_policy_t *policy) {
    memset(policy, 0, sizeof(*policy));
}
static void test_partial_srtp_cleanup(void) {
    g_srtp_api.srtp_create = fake_create;
    g_srtp_api.srtp_dealloc = fake_dealloc;
    g_srtp_api.crypto_policy_set_rtp_default = fake_policy;
    g_srtp_api.crypto_policy_set_rtcp_default = fake_policy;
    const char *offer = "INVITE sip:alluser@test.invalid SIP/2.0\r\n\r\nv=0\r\n"
        "m=audio 7078 RTP/SAVP 96\r\na=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\r\n"
        "m=video 9078 RTP/SAVP 96\r\na=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\r\n";
    for (fail_session = 1; fail_session <= 4; fail_session++) {
        session_attempts = session_frees = 0;
        handle_ring_invite(&g_bridge, -1, offer, "ha", "ha@test.invalid");
        assert(session_attempts == fail_session);
        assert(session_frees == fail_session - 1);
    }
}
static int test_bind(int fd, const struct sockaddr *address, socklen_t size) {
    (void)address; (void)size;
    struct sockaddr_in local = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    return bind(fd, (struct sockaddr *)&local, sizeof(local));
}
static int test_connect(int fd, const struct sockaddr *address, socklen_t size) {
    (void)address; (void)size;
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(dup2(pair[0], fd) == fd);
    close(pair[0]); peer = pair[1];
    atomic_store(&connecting, true);
    while (!atomic_load(&release_connect)) usleep(1000);
    const char *body = "v=0\r\nm=audio 7078 RTP/SAVP 98\r\na=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\r\nm=video 9078 RTP/SAVP 96\r\na=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\r\n";
    char response[2048];
    snprintf(response, sizeof(response), "SIP/2.0 200 OK\r\nContent-Length: 0\r\n\r\nSIP/2.0 200 OK\r\nContent-Length: %zu\r\n\r\n%s", strlen(body), body);
    assert(send(peer, response, strlen(response), 0) == (ssize_t)strlen(response));
    return 0;
}
bool c300x_device_media_takeover(const struct c300x_config *config) {
    (void)config; assert(!"cancelled setup must not take over device"); return false;
}
void c300x_device_media_stop(const struct c300x_config *config) { (void)config; }
bool c300x_device_media_start(const struct c300x_config *config) {
    (void)config; assert(!"cancelled setup must not renew media"); return false;
}
int c300x_device_user_media_identity(const char *hint, struct c300x_device_user_identity *identity) {
    (void)hint;
    strcpy(identity->domain, "test.invalid"); strcpy(identity->from_user, "ha");
    strcpy(identity->from_aor, "ha@test.invalid"); strcpy(identity->to_aor, "device@test.invalid");
    return 1;
}
static void *start_worker(void *arg) { (void)arg; start_result = start_media_session(&g_bridge); return NULL; }
static void *stop_worker(void *arg) { (void)arg; stop_media_session(true, true); return NULL; }

int main(void) {
    struct c300x_config config;
    c300x_default_config(&config);
    strcpy(config.video_sip_domain, "test.invalid");
    g_bridge.config = &config;
    g_bridge.video = c300x_video_create(&config, NULL, 0);
    assert(g_bridge.video);
    g_bridge.running = true;
    memset(g_bridge.ondemand_audio_srtp_in_key, 0xA5, sizeof(g_bridge.ondemand_audio_srtp_in_key));
    memset(g_bridge.ondemand_video_srtp_in_key, 0xA5, sizeof(g_bridge.ondemand_video_srtp_in_key));
    g_srtp_api.initialized = g_srtp_api.available = 1;
    test_partial_srtp_cleanup();
    pthread_t start, stop;
    assert(pthread_create(&start, NULL, start_worker, NULL) == 0);
    while (!atomic_load(&connecting)) usleep(1000);
    assert(pthread_create(&stop, NULL, stop_worker, NULL) == 0);
    for (;;) {
        pthread_mutex_lock(&g_bridge.mutex);
        bool invalidated = g_bridge.media_generation != 0;
        pthread_mutex_unlock(&g_bridge.mutex);
        if (invalidated) break;
        usleep(1000);
    }
    atomic_store(&release_connect, true);
    assert(pthread_join(start, NULL) == 0);
    assert(pthread_join(stop, NULL) == 0);
    assert(!start_result && g_bridge.ondemand_guard.explicit_stop);
    assert(!g_bridge.media_active && !g_bridge.media_starting);
    assert(!g_bridge.sip_monitor_started && !g_bridge.ondemand_media_started);
    assert(g_bridge.sip_fd == -1 && g_bridge.rtp_fd == -1);
    for (size_t i = 0; i < sizeof(g_bridge.ondemand_audio_srtp_in_key); i++) {
        assert(g_bridge.ondemand_audio_srtp_in_key[i] == 0 && g_bridge.ondemand_video_srtp_in_key[i] == 0);
    }
    close(peer);
    g_bridge.running = false;
    c300x_video_destroy(g_bridge.video);
    return 0;
}
