/* An on-demand start against a fake station media service: the real RTSP
 * handlers, the real bridge and the real device_media.c, linked with
 * --wrap=connect and --wrap=bind. The media service answers the client adds
 * like bt_av_media (accepted, or refused when the client is already there or
 * the call has no pipeline) and streams to the agent's port 250 ms after the
 * add that took effect, as the station does. The scenario decides which add
 * takes effect, or that none does. */
#include <assert.h>
#include <stdatomic.h>
#include <stdio.h>
#include <sys/socket.h>
#undef _POSIX_C_SOURCE
#include "../src/media_bridge.c"

#define FRAME_US 66667
#define IDR_EVERY 15
#define IDR_PARTS 60
#define STREAM_DELAY_US 250000
#define MAX_RX 4096
#define MAX_COMMANDS 64

enum scenario {EARLY, CLEARED, REFUSED_FIRST, NEVER};
static enum scenario scenario;

static long long now_us(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (long long)now.tv_sec * 1000000 + now.tv_nsec / 1000;
}

static void sleep_until_us(long long at_us) {
    long long left = at_us - now_us();
    if (left > 0) usleep((useconds_t)left);
}

/* ---- sockets: the media service on an ephemeral port, SIP on a pair ---- */

static struct sockaddr_in media_service;
static int sip_peer = -1;

int __real_connect(int, const struct sockaddr *, socklen_t);
int __real_bind(int, const struct sockaddr *, socklen_t);

int __wrap_connect(int fd, const struct sockaddr *address, socklen_t size) {
    const struct sockaddr_in *ipv4 = (const struct sockaddr_in *)address;
    if (address->sa_family == AF_INET && ntohs(ipv4->sin_port) == 30007) {
        return __real_connect(fd, (const struct sockaddr *)&media_service, sizeof(media_service));
    }
    (void)size;
    /* Flexisip: the REGISTER and the INVITE are answered at once. */
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(dup2(pair[0], fd) == fd);
    close(pair[0]);
    sip_peer = pair[1];
    const char *body = "v=0\r\nm=audio 7078 RTP/SAVP 0\r\na=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\r\nm=video 9078 RTP/SAVP 96\r\na=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\r\n";
    char response[2048];
    snprintf(response, sizeof(response), "SIP/2.0 200 OK\r\nContent-Length: 0\r\n\r\nSIP/2.0 200 OK\r\nContent-Length: %zu\r\n\r\n%s", strlen(body), body);
    assert(send(sip_peer, response, strlen(response), 0) == (ssize_t)strlen(response));
    return 0;
}

/* Fixed media ports would collide with parallel runs: UDP binds take any port. */
int __wrap_bind(int fd, const struct sockaddr *address, socklen_t size) {
    int type = 0;
    socklen_t type_len = sizeof(type);
    if (address != NULL && address->sa_family == AF_INET
        && getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &type_len) == 0 && type == SOCK_DGRAM) {
        struct sockaddr_in any = *(const struct sockaddr_in *)address;
        any.sin_port = 0;
        return __real_bind(fd, (struct sockaddr *)&any, sizeof(any));
    }
    return __real_bind(fd, address, size);
}

static int fake_ok(void) { return 0; }
static int fake_create(c300x_srtp_t *session, const c300x_srtp_policy_t *policy) {
    (void)policy; *session = (void *)1; return 0;
}
static int fake_session(c300x_srtp_t session) { (void)session; return 0; }
static int fake_packet(c300x_srtp_t session, void *packet, int *len) {
    (void)session; (void)packet; (void)len; return 0;
}
static void fake_policy(c300x_srtp_crypto_policy_t *policy) { memset(policy, 0, sizeof(*policy)); }

int c300x_device_user_media_identity(const char *hint, struct c300x_device_user_identity *identity) {
    (void)hint;
    strcpy(identity->domain, "test.invalid"); strcpy(identity->from_user, "ha");
    strcpy(identity->from_aor, "ha@test.invalid"); strcpy(identity->to_aor, "device@test.invalid");
    return 1;
}

/* ---- the station's streams to the agent's ports ---- */

static atomic_bool station_stop;
static atomic_llong video_at_us, audio_at_us;
static pthread_t video_thread, audio_thread, service_thread;
static atomic_bool video_started, audio_started;
static struct sockaddr_in video_to, audio_to;
static _Atomic uint32_t first_idr_ts;

static void station_send(int fd, const struct sockaddr_in *to, uint16_t *seq, uint32_t ts, uint32_t ssrc,
                         int payload_type, bool marker, const unsigned char *payload, size_t len) {
    unsigned char packet[1600];
    packet[0] = 0x80;
    packet[1] = (unsigned char)((marker ? 0x80 : 0) | payload_type);
    store_be16(packet + 2, (*seq)++);
    store_be32(packet + 4, ts);
    store_be32(packet + 8, ssrc);
    memcpy(packet + 12, payload, len);
    (void)sendto(fd, packet, len + 12, 0, (const struct sockaddr *)to, sizeof(*to));
}

/* A new stream starts with an IDR that the station paces over ~100 ms. */
static void *station_video(void *arg) {
    (void)arg;
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    uint16_t seq = 1281;
    uint32_t ts = 1308642029;
    unsigned char aud[2] = {0x09, 0xf0};
    unsigned char sps[10] = {0x67, 0x42, 0x80, 0x1f, 0xda, 0x02, 0x80, 0xf6, 0x80, 0x6d};
    unsigned char pps[4] = {0x68, 0xce, 0x06, 0xe2};
    unsigned char part[1276];
    long long t0 = atomic_load(&video_at_us);
    sleep_until_us(t0);
    first_idr_ts = ts;
    for (int frame = 0; !atomic_load(&station_stop); frame++) {
        sleep_until_us(t0 + (long long)frame * FRAME_US);
        bool idr = frame % IDR_EVERY == 0;
        int parts = idr ? IDR_PARTS : 4;
        station_send(fd, &video_to, &seq, ts, 0x6007c441, 96, false, aud, sizeof(aud));
        if (idr) {
            station_send(fd, &video_to, &seq, ts, 0x6007c441, 96, false, sps, sizeof(sps));
            station_send(fd, &video_to, &seq, ts, 0x6007c441, 96, false, pps, sizeof(pps));
        }
        for (int index = 0; index < parts; index++) {
            part[0] = 0x7c;
            part[1] = (unsigned char)((idr ? 5 : 1) | (index == 0 ? 0x80 : 0) | (index == parts - 1 ? 0x40 : 0));
            memset(part + 2, index, sizeof(part) - 2);
            station_send(fd, &video_to, &seq, ts, 0x6007c441, 96, index == parts - 1, part, sizeof(part));
            if (idr && index % 8 == 7) usleep(12000);
        }
        ts += 6000;
    }
    close(fd);
    return NULL;
}

static void *station_audio(void *arg) {
    (void)arg;
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    uint16_t seq = 7;
    uint32_t ts = 4242;
    unsigned char samples[160];
    memset(samples, 0xff, sizeof(samples));
    long long t0 = atomic_load(&audio_at_us);
    for (int packet = 0; !atomic_load(&station_stop); packet++) {
        sleep_until_us(t0 + (long long)packet * 20000);
        station_send(fd, &audio_to, &seq, ts, 0x1234, 0, false, samples, sizeof(samples));
        ts += 160;
    }
    close(fd);
    return NULL;
}

/* ---- the media service (bt_av_media on port 30007) ---- */

struct command {
    long long at_us;
    int branch; /* 0/1 video, 2 audio, -1 a removal */
    bool accepted;
};
static struct command commands[MAX_COMMANDS];
static atomic_int command_count;
static atomic_bool service_stop;
static int service_fd = -1;
static int video_adds;

static void bound_port(int fd, struct sockaddr_in *out) {
    socklen_t size = sizeof(*out);
    assert(getsockname(fd, (struct sockaddr *)out, &size) == 0);
}

/* Whether the station takes this video add, and whether its stream follows. */
static bool video_add_takes_effect(int add) {
    switch (scenario) {
    case EARLY: return add == 1;
    case CLEARED: return add == 2;          /* the call's setup cleared the first one */
    case REFUSED_FIRST: return add == 2;    /* no pipeline at the first add */
    case NEVER: return false;
    }
    return false;
}

static bool video_add_accepted(int add) {
    if (scenario == REFUSED_FIRST) return add == 2;
    return add == 1 || video_add_takes_effect(add);
}

static void answer(int fd) {
    char text[128];
    size_t used = 0;
    while (used + 1 < sizeof(text)) {
        struct pollfd ready = {.fd = fd, .events = POLLIN};
        assert(poll(&ready, 1, 2000) == 1);
        ssize_t n = recv(fd, text + used, sizeof(text) - used - 1, 0);
        assert(n > 0);
        used += (size_t)n;
        text[used] = '\0';
        if (strstr(text, "*##") != NULL) break;
    }
    int port = 0, branch = -1;
    bool add = sscanf(text, "*7*300#127#0#0#1#%d#%d*##", &port, &branch) == 2;
    bool removal = !add && strncmp(text, "*7*301#", 7) == 0;
    assert(add || removal);
    long long at = now_us();
    bool accepted = true;
    if (add && branch != 2) {
        video_adds++;
        accepted = video_add_accepted(video_adds);
        if (video_add_takes_effect(video_adds) && !video_started) {
            pthread_mutex_lock(&g_bridge.mutex);
            bound_port(g_bridge.rtp_fd, &video_to);
            pthread_mutex_unlock(&g_bridge.mutex);
            atomic_store(&video_at_us, at + STREAM_DELAY_US);
            assert(pthread_create(&video_thread, NULL, station_video, NULL) == 0);
            video_started = true;
        }
    } else if (add && !audio_started) {
        pthread_mutex_lock(&g_bridge.mutex);
        bound_port(g_bridge.audio_rtp_fd, &audio_to);
        pthread_mutex_unlock(&g_bridge.mutex);
        atomic_store(&audio_at_us, at);
        assert(pthread_create(&audio_thread, NULL, station_audio, NULL) == 0);
        audio_started = true;
    }
    int index = atomic_load(&command_count);
    assert(index < MAX_COMMANDS);
    commands[index] = (struct command){at, removal ? -1 : branch, accepted};
    atomic_store(&command_count, index + 1);
    const char *reply = accepted ? "*#*1##" : "*#*0##";
    assert(send(fd, reply, strlen(reply), MSG_NOSIGNAL) == (ssize_t)strlen(reply));
}

static void *media_service_thread(void *arg) {
    (void)arg;
    while (!atomic_load(&service_stop)) {
        struct pollfd ready = {.fd = service_fd, .events = POLLIN};
        if (poll(&ready, 1, 20) != 1) continue;
        int fd = accept(service_fd, NULL, NULL);
        assert(fd >= 0);
        answer(fd);
        close(fd);
    }
    return NULL;
}

/* ---- the RTSP client ---- */

static void *client_worker(void *arg) {
    struct sockaddr_storage peer = {0};
    int fd = *(int *)arg;
    int index = reserve_rtsp_client(&g_bridge, fd);
    assert(index >= 0);
    handle_rtsp_client(fd, &peer);
    release_rtsp_client(&g_bridge, fd, index);
    return NULL;
}

static void request(int fd, const char *method, const char *uri, const char *headers) {
    char message[1024], response[4096];
    snprintf(message, sizeof(message), "%s rtsp://127.0.0.1/doorbell%s RTSP/1.0\r\nCSeq: 1\r\n%s\r\n",
             method, uri, headers);
    assert(c300x_media_sip_send_all(fd, message, strlen(message)) > 0);
    size_t used = 0;
    for (;;) {
        ssize_t n = recv(fd, response + used, 1, 0);
        assert(n == 1);
        used++;
        response[used] = '\0';
        char *end = strstr(response, "\r\n\r\n");
        if (end && used >= (size_t)(end + 4 - response) + (size_t)c300x_media_sip_content_length(response)) break;
        assert(used + 1 < sizeof(response));
    }
    assert(strncmp(response, "RTSP/1.0 200 ", 13) == 0);
}

struct rx {
    uint16_t seq;
    uint32_t ts;
    uint8_t nal, fu;
};
static struct rx video[MAX_RX];
static size_t videos;

static void client_read(int fd, long long until_us) {
    unsigned char frame[4 + 65536];
    while (now_us() < until_us) {
        struct pollfd ready = {.fd = fd, .events = POLLIN};
        if (poll(&ready, 1, 20) != 1) continue;
        assert(recv(fd, frame, 4, MSG_WAITALL) == 4 && frame[0] == '$');
        size_t len = (size_t)frame[2] << 8 | frame[3];
        assert(len >= 12 && recv(fd, frame + 4, len, MSG_WAITALL) == (ssize_t)len);
        const unsigned char *packet = frame + 4;
        if (frame[1] != 2) continue;
        assert(len >= 14 && videos < MAX_RX);
        video[videos++] = (struct rx){load_be16(packet + 2), load_be32(packet + 4),
            (uint8_t)(packet[12] & 0x1f), (uint8_t)(packet[13] & 0x9f)};
    }
}

/* The client starts at the station's first IDR, with AUD, SPS, PPS and every
 * part of it, and its numbering never jumps. */
static void assert_clean_start(void) {
    assert(videos > IDR_PARTS + 3);
    assert(video[0].nal == 9 && video[1].nal == 7 && video[2].nal == 8);
    assert(video[3].nal == 28 && video[3].fu == 0x85 && video[0].ts == first_idr_ts);
    int parts = 0;
    for (size_t index = 0; index < videos; index++) {
        if (video[index].ts == first_idr_ts && video[index].nal == 28 && (video[index].fu & 0x1f) == 5) parts++;
        if (index > 0) assert(video[index].seq == (uint16_t)(video[index - 1].seq + 1));
    }
    assert(parts == IDR_PARTS);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    scenario = (enum scenario)atoi(argv[1]);
    alarm(30);

    service_fd = socket(AF_INET, SOCK_STREAM, 0);
    assert(service_fd >= 0);
    media_service = (struct sockaddr_in){.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    assert(__real_bind(service_fd, (struct sockaddr *)&media_service, sizeof(media_service)) == 0);
    assert(listen(service_fd, 8) == 0);
    bound_port(service_fd, &media_service);
    assert(pthread_create(&service_thread, NULL, media_service_thread, NULL) == 0);

    struct c300x_config config;
    c300x_default_config(&config);
    strcpy(config.video_sip_domain, "test.invalid");
    g_bridge.config = &config;
    g_bridge.video = c300x_video_create(&config, NULL, 0);
    assert(g_bridge.video);
    g_bridge.running = true;
    g_srtp_api = (c300x_srtp_api_t){
        .initialized = 1, .available = 1, .srtp_init = fake_ok, .srtp_create = fake_create,
        .srtp_dealloc = fake_session, .srtp_protect = fake_packet, .srtp_protect_rtcp = fake_packet,
        .srtp_unprotect = fake_packet, .srtp_unprotect_rtcp = fake_packet,
        .crypto_policy_set_rtp_default = fake_policy, .crypto_policy_set_rtcp_default = fake_policy,
    };

    int pair[2];
    pthread_t worker;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(pthread_create(&worker, NULL, client_worker, &pair[1]) == 0);
    request(pair[0], "DESCRIBE", "", "");
    request(pair[0], "SETUP", "/streamid=0", "Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n");
    request(pair[0], "SETUP", "/streamid=1", "Transport: RTP/AVP/TCP;unicast;interleaved=2-3\r\n");
    request(pair[0], "PLAY", "/", "");
    long long played_at = now_us();
    int before_play = atomic_load(&command_count);
    client_read(pair[0], played_at + 1200000);

    long long first_add = commands[0].at_us;
    long long stream_at = atomic_load(&video_at_us);
    printf("scenario %d: PLAY answered %lld ms after the first add", (int)scenario, (played_at - first_add) / 1000);
    if (video_started) printf(", %lld ms after the stream began", (played_at - stream_at) / 1000);
    printf("; commands before PLAY:");
    for (int index = 0; index < before_play; index++) {
        printf(" %s%s@%lld", commands[index].branch == 2 ? "audio" : "video",
               commands[index].accepted ? "" : "(refused)", (commands[index].at_us - first_add) / 1000);
    }
    putchar('\n');
    fflush(stdout);

    /* Before PLAY: video adds only, then exactly one audio add, last. */
    assert(before_play >= 2 && commands[0].branch != 2 && commands[before_play - 1].branch == 2);
    for (int index = 1; index < before_play - 1; index++) assert(commands[index].branch != 2);
    if (scenario == NEVER) {
        /* No stream: the accepted client stands after 1.5 s, as before. */
        assert(!video_started && before_play == 5);
        assert(played_at - first_add >= 1400000 && played_at - first_add < 2600000);
    } else {
        assert(video_started && videos > 0);
        /* The audio client follows the stream, PLAY follows the audio client
         * at once: no fixed wait is left between the stream and PLAY. */
        assert(commands[before_play - 1].at_us >= stream_at);
        assert(played_at >= stream_at && played_at - stream_at < 350000);
        assert_clean_start();
        if (scenario == EARLY) assert(before_play == 2);
        if (scenario == CLEARED) {
            /* An accepted add without a stream is repeated after 0.4 s. */
            assert(before_play == 3 && commands[1].at_us - first_add < 600000);
        }
        if (scenario == REFUSED_FIRST) {
            /* A refused add is repeated after 0.1 s. */
            assert(before_play == 3 && !commands[0].accepted && commands[1].at_us - first_add < 300000);
        }
    }

    atomic_store(&station_stop, true);
    if (video_started) assert(pthread_join(video_thread, NULL) == 0);
    if (audio_started) assert(pthread_join(audio_thread, NULL) == 0);
    c300x_media_session_stop(g_bridge.video);
    shutdown(pair[0], SHUT_RDWR);
    assert(pthread_join(worker, NULL) == 0);
    close(pair[0]);
    atomic_store(&service_stop, true);
    assert(pthread_join(service_thread, NULL) == 0);
    close(service_fd);
    if (sip_peer >= 0) close(sip_peer);
    g_bridge.running = false;
    c300x_video_destroy(g_bridge.video);
    puts("ok");
    return 0;
}
