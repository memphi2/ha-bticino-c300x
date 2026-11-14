/* Real RTSP handlers and thread ownership; device/SIP I/O is never invoked. */
#include <assert.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>

static int tracked_create(pthread_t *, const pthread_attr_t *, void *(*)(void *), void *);
static int tracked_join(pthread_t, void **);
static long long test_clock(void);
#define c300x_monotonic_ms test_clock
#define pthread_create tracked_create
#define pthread_join tracked_join
#undef _POSIX_C_SOURCE
/* The auth cases send many rejected requests on one connection; the unauth
 * cases switch to the real limit and a short lifetime. */
static int unauth_rejections = 1000;
static int unauth_lifetime = 30;
#define RTSP_UNAUTH_MAX_REJECTIONS unauth_rejections
#define RTSP_UNAUTH_LIFETIME_SECONDS unauth_lifetime
#include "../src/media_bridge.c"
#undef pthread_create
#undef pthread_join
#undef c300x_monotonic_ms
extern long long c300x_monotonic_ms(void);

static atomic_int joins;
static atomic_int renewals, clock_reads;
static atomic_llong clock_offset;
static long long test_clock(void) {
    atomic_fetch_add(&clock_reads, 1);
    return c300x_monotonic_ms() + atomic_load(&clock_offset);
}
static atomic_bool wait_for_stop;
static atomic_bool fail_create;

/* Keep device dependencies out of this executable, even on a failing test. */
bool c300x_device_media_takeover(const struct c300x_config *config) {
    (void)config;
    assert(!"unexpected device media start");
    return false;
}
void c300x_device_media_stop(const struct c300x_config *config) { (void)config; }
bool c300x_device_media_start(const struct c300x_config *config) {
    (void)config;
    assert(pthread_equal(pthread_self(), g_bridge.sip_thread));
    atomic_fetch_add(&renewals, 1);
    usleep(300000);
    return true;
}
int c300x_device_user_media_identity(const char *hint, struct c300x_device_user_identity *identity) {
    (void)hint;
    (void)identity;
    assert(!"unexpected SIP identity lookup");
    return 0;
}

static void *home_worker(void *arg) {
    media_bridge_t *bridge = arg;
    if (atomic_load(&wait_for_stop)) {
        for (;;) {
            pthread_mutex_lock(&bridge->mutex);
            bool stop = bridge->home_call_stop;
            pthread_mutex_unlock(&bridge->mutex);
            if (stop) break;
            usleep(1000);
        }
    }
    home_call_cleanup(bridge, -1, -1, -1);
    return NULL;
}

static int tracked_create(pthread_t *thread, const pthread_attr_t *attr,
                          void *(*worker)(void *), void *arg) {
    if (worker == home_call_thread_func) {
        if (atomic_load(&fail_create)) return EAGAIN;
        worker = home_worker;
    }
    return pthread_create(thread, attr, worker, arg);
}

static atomic_bool race_talkback_start;
static pthread_t racing_call;
static void *racing_call_worker(void *arg) {
    assert(start_call_talkback(arg));
    return NULL;
}

static int tracked_join(pthread_t thread, void **result) {
    atomic_fetch_add(&joins, 1);
    if (atomic_exchange(&race_talkback_start, false)) {
        /* A ring arrives while the session stop waits for the old proxy. */
        assert(pthread_create(&racing_call, NULL, racing_call_worker, &g_bridge) == 0);
        usleep(50000);
    }
    return pthread_join(thread, result);
}

static void *client_worker(void *arg) {
    struct sockaddr_storage peer = {0};
    struct sockaddr_in *ipv4 = (struct sockaddr_in *)&peer;
    ipv4->sin_family = AF_INET;
    ipv4->sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    handle_rtsp_client(*(int *)arg, &peer);
    return NULL;
}

static void request(int fd, const char *method, const char *headers, int status) {
    char message[2048], response[8192];
    snprintf(message, sizeof(message), "%s rtsp://127.0.0.1/doorbell-video RTSP/1.0\r\n"
        "CSeq: 42\r\n%s\r\n", method, headers);
    assert(send_all(fd, message, strlen(message)) > 0);
    size_t used = 0;
    response[0] = '\0';
    for (;;) {
        ssize_t n = recv(fd, response + used, sizeof(response) - used - 1, 0);
        assert(n > 0);
        used += (size_t)n;
        response[used] = '\0';
        char *end = strstr(response, "\r\n\r\n");
        if (end && used >= (size_t)(end + 4 - response)
            + (size_t)c300x_media_sip_content_length(response)) break;
        assert(used + 1 < sizeof(response));
    }
    char expected[32];
    snprintf(expected, sizeof(expected), "RTSP/1.0 %d ", status);
    assert(strncmp(response, expected, strlen(expected)) == 0);
    assert(strstr(response, "CSeq: 42\r\n"));
    if (status == 401) {
        assert(strstr(response, "401 Unauthorized\r\n"));
        assert(strstr(response, C300X_RTSP_AUTH_CHALLENGE));
    }
}

static bool peer_closed(int fd) {
    char byte;
    return recv(fd, &byte, 1, 0) == 0;
}

/* A request that never ends, sent a byte at a time, must not outlive the
 * lifetime of a connection that never authenticates. */
static void unauth_trickle_test(struct c300x_config *config) {
    int pair[2];
    pthread_t client;
    const char *slow = "OPTIONS rtsp://127.0.0.1/doorbell-video RTSP/1.0\r\nCSeq: 1\r\nX-Slow: ";
    strcpy(config->video_rtsp_username, "user");
    strcpy(config->video_rtsp_password, "pass");
    unauth_rejections = 5;
    unauth_lifetime = 1;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(pthread_create(&client, NULL, client_worker, &pair[1]) == 0);
    long long start = c300x_monotonic_ms();
    bool closed = false;
    for (size_t i = 0; !closed && c300x_monotonic_ms() - start < 4000; i++) {
        char byte = i < strlen(slow) ? slow[i] : 'x';
        if (send(pair[0], &byte, 1, MSG_NOSIGNAL) != 1) {
            closed = true;
            break;
        }
        struct pollfd peer = {.fd = pair[0], .events = POLLIN};
        closed = poll(&peer, 1, 300) == 1;
    }
    assert(closed);
    assert(c300x_monotonic_ms() - start < 3500);
    assert(pthread_join(client, NULL) == 0);
    close(pair[0]);
    close(pair[1]);
}

static void unauth_test(struct c300x_config *config, bool lifetime) {
    int pair[2];
    pthread_t client;
    strcpy(config->video_rtsp_username, "user");
    strcpy(config->video_rtsp_password, "pass");
    unauth_rejections = 5;
    unauth_lifetime = lifetime ? 1 : 30;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    struct timeval timeout = {5, 0};
    assert(setsockopt(pair[0], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
    assert(pthread_create(&client, NULL, client_worker, &pair[1]) == 0);
    if (lifetime) {
        /* Sending something often enough to beat the read timeout must not
         * keep a connection that never authenticates. */
        long long start = c300x_monotonic_ms();
        for (;;) {
            request(pair[0], "OPTIONS", "", 200);
            if (c300x_monotonic_ms() - start > 4000) break;
            usleep(300000);
            struct pollfd closed = {.fd = pair[0], .events = POLLIN};
            if (poll(&closed, 1, 0) == 1) break;
        }
        assert(peer_closed(pair[0]));
        assert(c300x_monotonic_ms() - start < 3500);
    } else {
        /* Four rejections are fine, the fifth closes the connection. */
        for (int i = 0; i < RTSP_UNAUTH_MAX_REJECTIONS; i++) {
            request(pair[0], "DESCRIBE", "Authorization: Basic dXNlcjpiYWQ=\r\n", 401);
        }
        assert(peer_closed(pair[0]));
    }
    assert(pthread_join(client, NULL) == 0);
    close(pair[0]);
    close(pair[1]);
    if (!lifetime) {
        /* One challenge and an answer is what a real client does. */
        assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
        assert(setsockopt(pair[0], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
        assert(pthread_create(&client, NULL, client_worker, &pair[1]) == 0);
        request(pair[0], "DESCRIBE", "", 401);
        request(pair[0], "DESCRIBE", "Authorization: Basic dXNlcjpwYXNz\r\n", 200);
        for (int i = 0; i < 2 * RTSP_UNAUTH_MAX_REJECTIONS; i++) {
            request(pair[0], "DESCRIBE", "", 401);
        }
        shutdown(pair[0], SHUT_RDWR);
        assert(pthread_join(client, NULL) == 0);
        close(pair[0]);
        close(pair[1]);
    }
}

static int client_count(void) {
    pthread_mutex_lock(&g_bridge.mutex);
    int count = rtsp_physical_client_count_locked(&g_bridge);
    pthread_mutex_unlock(&g_bridge.mutex);
    return count;
}

static void auth_test(struct c300x_config *config, bool legacy, bool pending_stop) {
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    struct timeval timeout = {3, 0};
    assert(setsockopt(pair[0], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
    if (!legacy) {
        strcpy(config->video_rtsp_username, "user");
        strcpy(config->video_rtsp_password, "pass");
    }
    pthread_t client;
    assert(pthread_create(&client, NULL, client_worker, &pair[1]) == 0);
    request(pair[0], "OPTIONS", "", 200);
    assert(client_count() == 0);
    if (!legacy) {
        const char *methods[] = {"DESCRIBE", "SETUP", "PLAY", "GET_PARAMETER", "TEARDOWN"};
        for (size_t i = 0; i < sizeof(methods) / sizeof(methods[0]); i++) {
            request(pair[0], methods[i], "", 401);
            request(pair[0], methods[i], "Authorization: Basic dXNlcjpiYWQ=\r\n", 401);
            assert(client_count() == 0);
        }
        /* Authentication failures cannot evict even a full set of parked slots. */
        int parked[C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS][2];
        pthread_mutex_lock(&g_bridge.mutex);
        for (size_t i = 0; i < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; i++) {
            assert(socketpair(AF_UNIX, SOCK_STREAM, 0, parked[i]) == 0);
            g_bridge.rtsp_clients[i].active = true;
            g_bridge.rtsp_clients[i].parked = true;
            g_bridge.rtsp_clients[i].fd = parked[i][1];
        }
        pthread_mutex_unlock(&g_bridge.mutex);
        request(pair[0], "DESCRIBE", "", 401);
        assert(client_count() == C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS);
        pthread_mutex_lock(&g_bridge.mutex);
        close_all_rtsp_clients_locked(&g_bridge);
        pthread_mutex_unlock(&g_bridge.mutex);
        for (size_t i = 0; i < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; i++) close(parked[i][0]);
    }
    if (pending_stop) {
        pthread_mutex_lock(&g_bridge.mutex);
        shutdown_all_rtsp_clients_locked(&g_bridge);
        pthread_mutex_unlock(&g_bridge.mutex);
        char byte;
        assert(recv(pair[0], &byte, 1, 0) == 0);
    } else {
        const char *auth = legacy ? "" : "Authorization: Basic dXNlcjpwYXNz\r\n";
        request(pair[0], "DESCRIBE", auth, 200);
        assert(client_count() == 1);
        char headers[256];
        snprintf(headers, sizeof(headers), "%sTransport: RTP/AVP;unicast;client_port=5000-5001\r\n", auth);
        request(pair[0], "SETUP", headers, 461);
        snprintf(headers, sizeof(headers), "%sTransport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n", auth);
        request(pair[0], "SETUP", headers, 200);
        if (!legacy) {
            request(pair[0], "TEARDOWN", "", 401);
            assert(client_count() == 1);
        }
        pthread_mutex_lock(&g_bridge.mutex);
        g_bridge.media_active = true; /* Existing synthetic session, no SIP/device start. */
        pthread_mutex_unlock(&g_bridge.mutex);
        request(pair[0], "PLAY", auth, 200);
        for (;;) {
            pthread_mutex_lock(&g_bridge.mutex);
            bool played = g_bridge.rtsp_clients[0].played;
            pthread_mutex_unlock(&g_bridge.mutex);
            if (played) break;
            usleep(1000);
        }
        unsigned char packet[12] = {0x80, 96}, received[16];
        forward_rtsp_packet(&g_bridge, packet, sizeof(packet), false);
        assert(recv(pair[0], received, sizeof(received), MSG_WAITALL) == 16);
        assert(received[0] == '$' && memcmp(received + 4, packet, 12) == 0);
        pthread_mutex_lock(&g_bridge.mutex);
        g_bridge.media_active = false;
        pthread_mutex_unlock(&g_bridge.mutex);
        request(pair[0], "TEARDOWN", auth, 200);
        assert(client_count() == 0);
    }
    shutdown(pair[0], SHUT_RDWR);
    close(pair[0]);
    assert(pthread_join(client, NULL) == 0);
    for (size_t i = 0; i < RTSP_CONNECTION_LIMIT; i++) assert(g_bridge.rtsp_connection_fds[i] == 0);
}

static void *stop_worker(void *arg) { c300x_media_home_call_stop(arg); return NULL; }

static void sip_join_test(void) {
    for (int i = 0; i < 20; i++) {
        int pair[2];
        assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
        pthread_mutex_lock(&g_bridge.mutex);
        g_bridge.sip_fd = pair[0];
        g_bridge.sip_monitor_started = g_bridge.sip_monitor_joinable = true;
        assert(pthread_create(&g_bridge.sip_thread, NULL, sip_monitor_thread, &g_bridge) == 0);
        pthread_mutex_unlock(&g_bridge.mutex);
        shutdown(pair[1], SHUT_RDWR);
        close(pair[1]);
        for (;;) {
            pthread_mutex_lock(&g_bridge.mutex);
            bool running = g_bridge.sip_monitor_started;
            pthread_mutex_unlock(&g_bridge.mutex);
            if (!running) break;
            usleep(1000);
        }
        stop_media_session(false, false);
        assert(atomic_load(&joins) == i + 1);
        assert(!g_bridge.sip_monitor_joinable);
    }
}

static void sip_renew_test(void) {
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    g_bridge.sip_fd = pair[0];
    g_bridge.media_active = true;
    g_bridge.sip_monitor_started = g_bridge.sip_monitor_joinable = true;
    atomic_store(&clock_reads, 0);
    assert(pthread_create(&g_bridge.sip_thread, NULL, sip_monitor_thread, &g_bridge) == 0);
    while (atomic_load(&clock_reads) == 0) usleep(1000);
    atomic_store(&clock_offset, 21000);
    while (atomic_load(&renewals) == 0) usleep(1000);
    stop_media_session(false, false);
    assert(atomic_load(&renewals) == 1);
    close(pair[1]);
}

static void *forward_worker(void *arg) {
    (void)arg;
    unsigned char packet[12] = {0x80, 96};
    forward_rtsp_packet(&g_bridge, packet, sizeof(packet), false);
    return NULL;
}

static void stalled_client_test(void) {
    int slow[2], healthy[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, slow) == 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, healthy) == 0);
    int small = 4096;
    assert(setsockopt(slow[0], SOL_SOCKET, SO_SNDBUF, &small, sizeof(small)) == 0);
    unsigned char padding[4096] = {0};
    while (send(slow[0], padding, sizeof(padding), MSG_DONTWAIT | MSG_NOSIGNAL) > 0) {}
    g_bridge.rtsp_clients[0] = (rtsp_client_slot_t){.active = true, .played = true,
        .fd = slow[0], .transport_tcp = true};
    g_bridge.rtsp_clients[1] = (rtsp_client_slot_t){.active = true, .played = true,
        .fd = healthy[0], .transport_tcp = true};
    long long start = c300x_monotonic_ms();
    forward_worker(NULL);
    assert(c300x_monotonic_ms() - start < 1500);
    assert(recv(healthy[1], padding, sizeof(padding), MSG_DONTWAIT) == 16);
    g_bridge.media_active = g_bridge.relay_started = true;
    assert(pthread_create(&g_bridge.relay_thread, NULL, forward_worker, NULL) == 0);
    stop_media_session(true, true);
    assert(c300x_monotonic_ms() - start < 2000);
    close(slow[0]); close(slow[1]); close(healthy[0]); close(healthy[1]);
}

static void home_test(struct c300x_config *config, struct c300x_video *video, const char *mode) {
    config->video_enabled = 1;
    bool concurrent = strcmp(mode, "home_concurrent") == 0;
    bool restart = strcmp(mode, "home_restart") == 0;
    atomic_store(&wait_for_stop, concurrent);
    for (int i = 0; i < 20; i++) {
        assert(c300x_media_home_call_start(config, video, 0));
        if (concurrent) {
            pthread_t a, b;
            assert(pthread_create(&a, NULL, stop_worker, video) == 0);
            assert(pthread_create(&b, NULL, stop_worker, video) == 0);
            assert(pthread_join(a, NULL) == 0);
            assert(pthread_join(b, NULL) == 0);
        } else {
            for (;;) {
                pthread_mutex_lock(&g_bridge.mutex);
                bool running = g_bridge.home_call_started;
                pthread_mutex_unlock(&g_bridge.mutex);
                if (!running) break;
                usleep(1000);
            }
            if (!restart) c300x_media_home_call_stop(video);
        }
        assert(atomic_load(&joins) == (restart ? i : i + 1));
    }
    c300x_media_home_call_stop(video);
    assert(atomic_load(&joins) == 20);
    assert(!g_bridge.home_call_joinable && !g_bridge.home_call_joining);
    atomic_store(&fail_create, true);
    assert(!c300x_media_home_call_start(config, video, 0));
    c300x_media_home_call_stop(video);
    assert(atomic_load(&joins) == 20 && !g_bridge.home_call_joinable);
}

static void serve_ffprobe(struct c300x_config *config, struct c300x_video *video) {
    config->video_rtsp_port = 0;
    strcpy(config->video_rtsp_username, "user");
    strcpy(config->video_rtsp_password, "pass");
    g_bridge.running = false;
    assert(c300x_media_bridge_start(config, video));
    pthread_mutex_lock(&g_bridge.mutex);
    g_bridge.media_active = true;
    struct sockaddr_storage address;
    socklen_t len = sizeof(address);
    assert(getsockname(g_bridge.listen_fd, (struct sockaddr *)&address, &len) == 0);
    unsigned port = address.ss_family == AF_INET6
        ? ntohs(((struct sockaddr_in6 *)&address)->sin6_port)
        : ntohs(((struct sockaddr_in *)&address)->sin_port);
    pthread_mutex_unlock(&g_bridge.mutex);
    printf("%u\n", port);
    fflush(stdout);
    (void)getchar();
    c300x_media_bridge_stop(video);
    printf("describes=%llu plays=%llu\n", g_bridge.rtsp_describe_requests, g_bridge.rtsp_play_requests);
}

/* A call that starts its talkback proxy during a session stop must end with
 * one running proxy that owns an open socket, and the stop must return. */
static void talkback_stop_race_test(void) {
    alarm(10);
    assert(start_talkback_proxy(&g_bridge));
    for (;;) {
        pthread_mutex_lock(&g_bridge.mutex);
        bool bound = g_bridge.talkback_fd >= 0;
        pthread_mutex_unlock(&g_bridge.mutex);
        if (bound) break;
        usleep(1000);
    }
    atomic_store(&race_talkback_start, true);
    stop_media_session(false, false);
    assert(pthread_join(racing_call, NULL) == 0);
    for (int i = 0; i < 2000; i++) {
        pthread_mutex_lock(&g_bridge.mutex);
        bool bound = g_bridge.talkback_fd >= 0;
        pthread_mutex_unlock(&g_bridge.mutex);
        if (bound) break;
        usleep(1000);
    }
    pthread_mutex_lock(&g_bridge.mutex);
    assert(g_bridge.talkback_started && !g_bridge.talkback_stop);
    assert(g_bridge.talkback_fd >= 0 && fcntl(g_bridge.talkback_fd, F_GETFD) != -1);
    pthread_mutex_unlock(&g_bridge.mutex);
    stop_media_session(false, false);
    assert(!g_bridge.talkback_started && g_bridge.talkback_fd < 0);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    struct c300x_config config;
    c300x_default_config(&config);
    struct c300x_video *video = c300x_video_create(&config, NULL, 0);
    assert(video);
    g_bridge.config = &config;
    g_bridge.video = video;
    g_bridge.running = true;
    if (strcmp(argv[1], "serve") == 0) {
        serve_ffprobe(&config, video);
    } else if (strcmp(argv[1], "interleaved") == 0) {
        assert(parse_interleaved_channel("RTP/AVP/TCP;unicast;interleaved=0-1") == 0);
        assert(parse_interleaved_channel("RTP/AVP/TCP;interleaved=4-5") == 4);
        assert(parse_interleaved_channel("RTP/AVP/TCP;interleaved=254-255") == 254);
        assert(parse_interleaved_channel("RTP/AVP/TCP;unicast") == -1);
        assert(parse_interleaved_channel("RTP/AVP/TCP;interleaved=255-256") == -1);
        assert(parse_interleaved_channel("RTP/AVP/TCP;interleaved=2147483647") == -1);
        assert(parse_interleaved_channel("RTP/AVP/TCP;interleaved=99999999999999999999") == -1);
        assert(parse_interleaved_channel("RTP/AVP/TCP;interleaved=-3") == -1);
        assert(parse_interleaved_channel("RTP/AVP/TCP;interleaved=abc") == -1);
    } else if (strcmp(argv[1], "unauth_rejections") == 0) {
        unauth_test(&config, false);
    } else if (strcmp(argv[1], "unauth_lifetime") == 0) {
        unauth_test(&config, true);
    } else if (strcmp(argv[1], "unauth_trickle") == 0) {
        unauth_trickle_test(&config);
    } else if (strcmp(argv[1], "stalled_client") == 0) {
        stalled_client_test();
    } else if (strcmp(argv[1], "read_timeout") == 0) {
        extern long long c300x_monotonic_ms(void);
        long long now = c300x_monotonic_ms();
        assert(c300x_rtsp_read_timeout(0, 0, 0) == 30);
        assert(c300x_rtsp_read_timeout(0, RTSP_IDLE_TIMEOUT_SECONDS, 0) == 180);
        assert(c300x_rtsp_read_timeout(RTSP_TEARDOWN_CLOSE_WAIT_SECONDS, 180, 0) == 3);
        assert(c300x_rtsp_read_timeout(0, 180, now + 5000) == 5);
        assert(c300x_rtsp_read_timeout(0, 180, now + 400000) == 180);
        assert(c300x_rtsp_read_timeout(0, 180, now - 1) == 0);
    } else if (strcmp(argv[1], "talkback_stop_race") == 0) {
        talkback_stop_race_test();
    } else if (strcmp(argv[1], "sip_join") == 0) {
        sip_join_test();
    } else if (strcmp(argv[1], "sip_renew") == 0) {
        sip_renew_test();
    } else if (strncmp(argv[1], "home_", 5) == 0) {
        home_test(&config, video, argv[1]);
    } else {
        auth_test(&config, strcmp(argv[1], "legacy") == 0, strcmp(argv[1], "pending_stop") == 0);
    }
    g_bridge.running = false;
    c300x_video_destroy(video);
    return 0;
}
