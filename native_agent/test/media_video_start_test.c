/* An on-demand start against a fake station: it streams from the first
 * media command on, through the takeover's waits, with a large first IDR.
 * The first client must get that IDR whole, a later one the newest IDR from
 * the cache, both with their own continuous numbering. Real RTSP handlers;
 * SIP and the device media service are faked. */
#include <assert.h>
#include <stdatomic.h>
#include <stdio.h>
#include <sys/socket.h>
static int test_connect(int, const struct sockaddr *, socklen_t);
static int test_bind(int, const struct sockaddr *, socklen_t);
static int test_setsockopt(int, int, int, const void *, socklen_t);
#define connect test_connect
#define bind test_bind
#define setsockopt test_setsockopt
#undef _POSIX_C_SOURCE
#include "../src/media_bridge.c"
#undef connect
#undef bind
#undef setsockopt

#define FRAME_US 66667
#define IDR_EVERY 30
#define FIRST_IDR_PARTS 121
#define LATER_IDR_PARTS 40
#define MAX_RX 4096
/* net.core.rmem_max of the 4.9 kernels of firmware 1.7.19, 2.0.2 and C100X. */
#define DEVICE_RMEM_MAX 212992

/* Parts of the first frames of a new station stream, from a capture: the
 * encoder spends about 490 KB on its first second. */
static const int first_frame_parts[] = {FIRST_IDR_PARTS, 1, 1, 1, 1, 90, 1, 73, 1, 55, 1, 32, 5, 1};

static int sip_peer = -1;
static int test_setsockopt(int fd, int level, int name, const void *value, socklen_t size) {
    if (level == SOL_SOCKET && name == SO_RCVBUF && size == sizeof(int) && *(const int *)value > DEVICE_RMEM_MAX) {
        int capped = DEVICE_RMEM_MAX;
        return setsockopt(fd, level, name, &capped, sizeof(capped));
    }
    return setsockopt(fd, level, name, value, size);
}
/* Fixed media ports would collide with parallel runs: UDP binds take any port. */
static int test_bind(int fd, const struct sockaddr *address, socklen_t size) {
    int type = 0;
    socklen_t type_len = sizeof(type);
    if (address != NULL && address->sa_family == AF_INET
        && getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &type_len) == 0 && type == SOCK_DGRAM) {
        struct sockaddr_in any = *(const struct sockaddr_in *)address;
        any.sin_port = 0;
        return bind(fd, (struct sockaddr *)&any, sizeof(any));
    }
    return bind(fd, address, size);
}
/* Flexisip: the REGISTER and the INVITE are answered at once. */
static int test_connect(int fd, const struct sockaddr *address, socklen_t size) {
    (void)address; (void)size;
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

/* ---- the station: H.264 to the agent's video port, PCMU to its audio port ---- */

static atomic_bool station_stop;
static pthread_t video_thread, audio_thread;
static struct sockaddr_in video_to, audio_to;
static long long station_t0;
static uint32_t idr_ts[8];
static atomic_int idrs_sent;

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

static void sleep_until_us(long long at_us) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    long long left = at_us - ((long long)now.tv_sec * 1000000 + now.tv_nsec / 1000);
    if (left > 0) usleep((useconds_t)left);
}

static long long now_us(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (long long)now.tv_sec * 1000000 + now.tv_nsec / 1000;
}

static void *station_video(void *arg) {
    (void)arg;
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    uint16_t seq = 1281;
    uint32_t ts = 1308642029;
    unsigned char aud[2] = {0x09, 0xf0};
    unsigned char sps[10] = {0x67, 0x42, 0x80, 0x1f, 0xda, 0x02, 0x80, 0xf6, 0x80, 0x6d};
    unsigned char pps[4] = {0x68, 0xce, 0x06, 0xe2};
    unsigned char part[1276];
    for (int frame = 0; !atomic_load(&station_stop); frame++) {
        sleep_until_us(station_t0 + (long long)frame * FRAME_US);
        bool idr = frame % IDR_EVERY == 0;
        int parts = idr ? LATER_IDR_PARTS : 4;
        if (frame < (int)(sizeof(first_frame_parts) / sizeof(first_frame_parts[0]))) parts = first_frame_parts[frame];
        station_send(fd, &video_to, &seq, ts, 0x6007c441, 96, false, aud, sizeof(aud));
        if (idr) {
            idr_ts[atomic_load(&idrs_sent) % 8] = ts;
            atomic_fetch_add(&idrs_sent, 1);
            station_send(fd, &video_to, &seq, ts, 0x6007c441, 96, false, sps, sizeof(sps));
            station_send(fd, &video_to, &seq, ts, 0x6007c441, 96, false, pps, sizeof(pps));
        }
        for (int index = 0; index < parts; index++) {
            part[0] = 0x7c;
            part[1] = (unsigned char)((idr ? 5 : 1) | (index == 0 ? 0x80 : 0) | (index == parts - 1 ? 0x40 : 0));
            memset(part + 2, index, sizeof(part) - 2);
            station_send(fd, &video_to, &seq, ts, 0x6007c441, 96, index == parts - 1, part, sizeof(part));
            /* The station paces a large IDR over about 150 ms. */
            if (idr && index % 8 == 7) usleep(8000);
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
    for (int packet = 0; !atomic_load(&station_stop); packet++) {
        sleep_until_us(station_t0 + (long long)packet * 20000);
        station_send(fd, &audio_to, &seq, ts, 0x1234, 0, false, samples, sizeof(samples));
        ts += 160;
    }
    close(fd);
    return NULL;
}

static atomic_int takeovers;
/* The device media service: the stream begins with the first command; the
 * takeover then waits, here shortened, as device_media.c does. */
bool c300x_device_media_takeover(const struct c300x_config *config) {
    (void)config;
    atomic_fetch_add(&takeovers, 1);
    struct sockaddr_in bound;
    socklen_t bound_len = sizeof(bound);
    pthread_mutex_lock(&g_bridge.mutex);
    assert(getsockname(g_bridge.rtp_fd, (struct sockaddr *)&bound, &bound_len) == 0);
    video_to = bound;
    bound_len = sizeof(bound);
    assert(getsockname(g_bridge.audio_rtp_fd, (struct sockaddr *)&bound, &bound_len) == 0);
    audio_to = bound;
    pthread_mutex_unlock(&g_bridge.mutex);
    station_t0 = now_us();
    assert(pthread_create(&video_thread, NULL, station_video, NULL) == 0);
    assert(pthread_create(&audio_thread, NULL, station_audio, NULL) == 0);
    usleep(150000);
    usleep(300000);
    usleep(150000);
    return true;
}
bool c300x_device_media_start(const struct c300x_config *config) { (void)config; return true; }
void c300x_device_media_stop(const struct c300x_config *config) { (void)config; }

/* ---- RTSP clients ---- */

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
    uint32_t ts, ssrc;
    uint8_t nal, fu;
};

struct client {
    int pair[2];
    pthread_t thread, reader;
    long long read_until_us;
    struct rx video[MAX_RX];
    size_t videos, audios;
    uint16_t audio_seq;
};

static void client_play(struct client *client) {
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, client->pair) == 0);
    assert(pthread_create(&client->thread, NULL, client_worker, &client->pair[1]) == 0);
    request(client->pair[0], "DESCRIBE", "", "");
    request(client->pair[0], "SETUP", "/streamid=0", "Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n");
    request(client->pair[0], "SETUP", "/streamid=1", "Transport: RTP/AVP/TCP;unicast;interleaved=2-3\r\n");
    request(client->pair[0], "PLAY", "/", "");
}

/* Reads interleaved frames until the deadline. */
static void client_read(struct client *client, long long until_us) {
    unsigned char frame[4 + 65536];
    while (now_us() < until_us) {
        struct pollfd ready = {.fd = client->pair[0], .events = POLLIN};
        if (poll(&ready, 1, 20) != 1) continue;
        assert(recv(client->pair[0], frame, 4, MSG_WAITALL) == 4 && frame[0] == '$');
        size_t len = (size_t)frame[2] << 8 | frame[3];
        assert(len >= 12 && recv(client->pair[0], frame + 4, len, MSG_WAITALL) == (ssize_t)len);
        const unsigned char *packet = frame + 4;
        if (frame[1] == 0) {
            assert(client->audios == 0 || load_be16(packet + 2) == (uint16_t)(client->audio_seq + 1));
            client->audio_seq = load_be16(packet + 2);
            client->audios++;
            continue;
        }
        assert(frame[1] == 2 && len >= 14 && client->videos < MAX_RX);
        client->video[client->videos++] = (struct rx){load_be16(packet + 2), load_be32(packet + 4),
            load_be32(packet + 8), (uint8_t)(packet[12] & 0x1f), (uint8_t)(packet[13] & 0x9f)};
    }
}

static void *client_reader(void *arg) {
    struct client *client = arg;
    client_read(client, client->read_until_us);
    return NULL;
}

/* The client starts at the IDR with this station timestamp, with AUD, SPS,
 * PPS and every part of it, and its numbering never jumps. */
static void assert_clean_start(const struct client *client, uint32_t first_ts, int idr_parts) {
    const struct rx *rx = client->video;
    size_t count = client->videos;
    assert(count > (size_t)idr_parts + 3);
    assert(rx[0].nal == 9 && rx[1].nal == 7 && rx[2].nal == 8 && rx[3].nal == 28 && rx[3].fu == 0x85);
    assert(rx[0].ts == first_ts);
    int parts = 0;
    bool live = false;
    for (size_t index = 0; index < count; index++) {
        assert(rx[index].ssrc == rx[0].ssrc);
        if (rx[index].ts == first_ts && rx[index].nal == 28 && (rx[index].fu & 0x1f) == 5) parts++;
        if (index == 0) continue;
        assert(rx[index].seq == (uint16_t)(rx[index - 1].seq + 1));
        uint32_t step = rx[index].ts - rx[index - 1].ts;
        /* Cached frames 1 ms apart, then the station's 15 frames a second. */
        assert(step == 0 || (step == 90 && !live) || step == 6000);
        if (step == 6000) live = true;
    }
    assert(parts == idr_parts);
}

static struct client first, second;

int main(void) {
    alarm(30);
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

    /* PLAY starts the session; the takeover runs with the station streaming. */
    client_play(&first);
    assert(atomic_load(&takeovers) == 1);
    long long end_us = station_t0 + (long long)(2 * IDR_EVERY - 4) * FRAME_US;
    first.read_until_us = end_us;
    assert(pthread_create(&first.reader, NULL, client_reader, &first) == 0);

    /* A second client 0.4 s after the second IDR gets that IDR from the cache. */
    sleep_until_us(station_t0 + (long long)(IDR_EVERY + 6) * FRAME_US);
    assert(atomic_load(&idrs_sent) == 2);
    client_play(&second);
    second.read_until_us = end_us;
    assert(pthread_create(&second.reader, NULL, client_reader, &second) == 0);
    assert(pthread_join(first.reader, NULL) == 0);
    assert(pthread_join(second.reader, NULL) == 0);
    assert(atomic_load(&idrs_sent) == 2);
    assert_clean_start(&first, idr_ts[0], FIRST_IDR_PARTS);
    assert_clean_start(&second, idr_ts[1], LATER_IDR_PARTS);
    assert(first.audios >= 100 && second.audios >= 40);

    atomic_store(&station_stop, true);
    assert(pthread_join(video_thread, NULL) == 0);
    assert(pthread_join(audio_thread, NULL) == 0);
    c300x_media_session_stop(g_bridge.video);
    shutdown(first.pair[0], SHUT_RDWR);
    shutdown(second.pair[0], SHUT_RDWR);
    assert(pthread_join(first.thread, NULL) == 0);
    assert(pthread_join(second.thread, NULL) == 0);
    close(first.pair[0]);
    close(second.pair[0]);
    close(sip_peer);
    g_bridge.running = false;
    c300x_video_destroy(g_bridge.video);
    puts("ok");
    return 0;
}
