/* Replays device-captured ring sequences against the real agent code: the
 * HTTP event loop (bus frames, event payloads), video state and media bridge.
 * A fake flexisip/station answers SIP on loopback; only device files, SRTP
 * and the MQTT output are stubbed. */
#include <assert.h>
#include <stdatomic.h>
#include "../src/http.c"
#include "../src/device_media.h"
#include "../src/device_user.h"
#include "../src/media_sip.h"
#include "../src/media_sip_io.h"
#include "../src/media_gop_cache.h"
#include "../src/media_rtsp_io.h"
#include "../src/media_unit.h"

#define SIP_BUFFER_SIZE 8192

#define WAIT_MS 4000

/* The agent's ring leg waits AGENT_RING_REPLY_SECONDS for the 200 to its
 * REGISTER and tries again AGENT_RING_RETRY_SECONDS later; the build passes both
 * from media_bridge.c. A loaded host can miss the first answer, so the start
 * waits for one lost attempt, the pause and the next attempt's answer. */
#if !defined(AGENT_RING_REPLY_SECONDS) || !defined(AGENT_RING_RETRY_SECONDS)
#error "build with the agent's -DAGENT_RING_REPLY_SECONDS and -DAGENT_RING_RETRY_SECONDS"
#endif
#define RING_REGISTERED_WAIT_MS ((AGENT_RING_REPLY_SECONDS + AGENT_RING_RETRY_SECONDS) * 1000 + WAIT_MS)

/* ---- stubs for device-only functions (linked with --wrap) ---- */

int __wrap_c300x_device_user_media_identity(const char *hint, struct c300x_device_user_identity *identity) {
    (void)hint;
    memset(identity, 0, sizeof(*identity));
    snprintf(identity->domain, sizeof(identity->domain), "test.local");
    snprintf(identity->from_user, sizeof(identity->from_user), "homeassistant");
    snprintf(identity->from_aor, sizeof(identity->from_aor), "homeassistant@test.local");
    snprintf(identity->to_aor, sizeof(identity->to_aor), "c300x@test.local");
    return 1;
}
bool __wrap_c300x_device_media_takeover(const struct c300x_config *config, c300x_device_media_video_wait_fn wait, void *context) { (void)config; (void)wait; (void)context; return true; }
bool __wrap_c300x_device_media_start(const struct c300x_config *config) { (void)config; return true; }
void __wrap_c300x_device_media_stop(const struct c300x_config *config) { (void)config; }
int __wrap_c300x_audio_codec_device_is_pcmu(void) { return 1; }

static atomic_llong clock_offset;
long long __real_c300x_monotonic_ms(void);
long long __wrap_c300x_monotonic_ms(void) { return __real_c300x_monotonic_ms() + atomic_load(&clock_offset); }

/* libsrtp.so.1 is not on the build host: a pass-through SRTP. */
static int fake_srtp_ok(void) { return 0; }
static int fake_srtp_create(void **session, const void *policy) { (void)policy; *session = (void *)1; return 0; }
static int fake_srtp_dealloc(void *session) { (void)session; return 0; }
static int fake_srtp_packet(void *session, void *packet, int *len) { (void)session; (void)packet; (void)len; return 0; }
static void fake_policy(void *policy) { (void)policy; }
static char fake_srtp_handle;
void *__real_dlopen(const char *name, int flags);
void *__real_dlsym(void *handle, const char *name);
int __real_dlclose(void *handle);
void *__wrap_dlopen(const char *name, int flags) {
    if (name != NULL && strcmp(name, "libsrtp.so.1") == 0) return &fake_srtp_handle;
    (void)flags;
    return NULL;
}
void *__wrap_dlsym(void *handle, const char *name) {
    if (handle != &fake_srtp_handle) return __real_dlsym(handle, name);
    if (strcmp(name, "srtp_init") == 0) return (void *)fake_srtp_ok;
    if (strcmp(name, "srtp_create") == 0) return (void *)fake_srtp_create;
    if (strcmp(name, "srtp_dealloc") == 0) return (void *)fake_srtp_dealloc;
    if (strncmp(name, "srtp_", 5) == 0) return (void *)fake_srtp_packet;
    if (strncmp(name, "crypto_policy_set_", 18) == 0) return (void *)fake_policy;
    return NULL;
}
int __wrap_dlclose(void *handle) { return handle == &fake_srtp_handle ? 0 : __real_dlclose(handle); }

/* Fixed RTP/RTCP/talkback ports would collide with parallel test runs. */
int __real_bind(int fd, const struct sockaddr *address, socklen_t length);
int __wrap_bind(int fd, const struct sockaddr *address, socklen_t length) {
    int type = 0;
    socklen_t type_len = sizeof(type);
    if (address != NULL && address->sa_family == AF_INET && length >= (socklen_t)sizeof(struct sockaddr_in)
        && getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &type_len) == 0 && type == SOCK_DGRAM) {
        struct sockaddr_in any = *(const struct sockaddr_in *)address;
        any.sin_port = 0;
        return __real_bind(fd, (const struct sockaddr *)&any, sizeof(any));
    }
    return __real_bind(fd, address, length);
}

/* ---- published events (the HA webhook payloads) ---- */

#define MAX_EVENTS 64
static pthread_mutex_t events_mutex = PTHREAD_MUTEX_INITIALIZER;
static char event_types[MAX_EVENTS][64];
static char event_data[MAX_EVENTS][4096];
static int event_total;

void __wrap_c300x_mqtt_publish_event(struct c300x_mqtt *mqtt, const struct c300x_config *config,
                                     const char *type, const char *event_json, const char *data_json) {
    (void)mqtt; (void)config; (void)event_json;
    pthread_mutex_lock(&events_mutex);
    if (event_total < MAX_EVENTS) {
        snprintf(event_types[event_total], sizeof(event_types[0]), "%s", type);
        snprintf(event_data[event_total], sizeof(event_data[0]), "%s", data_json);
        event_total++;
    }
    pthread_mutex_unlock(&events_mutex);
}

static int count_events(const char *type) {
    int count = 0;
    pthread_mutex_lock(&events_mutex);
    for (int i = 0; i < event_total; i++) count += strcmp(event_types[i], type) == 0;
    pthread_mutex_unlock(&events_mutex);
    return count;
}

/* Waits for the n-th event of this type and returns a copy of its payload. */
static void wait_event(const char *type, int nth, char *data, size_t data_len) {
    long long deadline = __real_c300x_monotonic_ms() + WAIT_MS;
    for (;;) {
        pthread_mutex_lock(&events_mutex);
        int seen = 0;
        for (int i = 0; i < event_total; i++) {
            if (strcmp(event_types[i], type) == 0 && ++seen == nth) {
                if (data) snprintf(data, data_len, "%s", event_data[i]);
                pthread_mutex_unlock(&events_mutex);
                return;
            }
        }
        pthread_mutex_unlock(&events_mutex);
        if (__real_c300x_monotonic_ms() > deadline) {
            fprintf(stderr, "timed out waiting for %s #%d\n", type, nth);
            abort();
        }
        usleep(5000);
    }
}

static bool payload_external(const char *data) {
    return strstr(data, "\"external_media_active\":true") != NULL;
}

/* ---- the fake station behind flexisip ---- */

static int sip_listen_fd = -1;
static atomic_int ring_fd = -1;
static atomic_int ring_registers;
static atomic_int lose_ring_register;
static atomic_int ondemand_invites;
static atomic_int station_byes; /* BYEs the agent sent the station */
static atomic_int station_busy = 1;
/* The call the station is busy with ends before its 486 answer, or right
 * after it while the agent still cleans up the failed start. */
static atomic_int end_before_486, end_after_486;
static void bus(const char *frame);
static pthread_mutex_t codes_mutex = PTHREAD_MUTEX_INITIALIZER;
/* In order: "I<DEVADDR>" per INVITE the station got, "B" per BYE the agent
 * sent, "G" per drop of the on-demand view's cached frames. */
static char station_log[512];

static void log_station(const char *entry) {
    pthread_mutex_lock(&codes_mutex);
    size_t used = strlen(station_log);
    snprintf(station_log + used, sizeof(station_log) - used, "%s%s", used ? " " : "", entry);
    pthread_mutex_unlock(&codes_mutex);
}

/* The BYE as the agent sends it: it does not wait for the station's answer,
 * which comes on another connection than the next INVITE. */
void __real_c300x_media_sip_send_bye(int fd, const char *from_aor, const char *to_aor, const char *local_ip,
                                     uint16_t local_port, const char *transport, const char *to_header,
                                     const char *from_tag, const char *call_id, const char *contact_uri);
void __wrap_c300x_media_sip_send_bye(int fd, const char *from_aor, const char *to_aor, const char *local_ip,
                                     uint16_t local_port, const char *transport, const char *to_header,
                                     const char *from_tag, const char *call_id, const char *contact_uri) {
    log_station("B");
    __real_c300x_media_sip_send_bye(fd, from_aor, to_aor, local_ip, local_port, transport, to_header, from_tag,
                                    call_id, contact_uri);
}

void __real_c300x_media_gop_reset(enum c300x_media_gop_source source);
void __wrap_c300x_media_gop_reset(enum c300x_media_gop_source source) {
    if (source == C300X_MEDIA_GOP_ONDEMAND) log_station("G");
    __real_c300x_media_gop_reset(source);
}
/* 1: the next PLAY answer waits after it is sent (2) until the case sets 0. */
static atomic_int hold_play;
void __real_send_rtsp_response(struct c300x_rtsp_writer *writer, int fd, int status, const char *cseq,
                               const char *headers, const char *body);
void __wrap_send_rtsp_response(struct c300x_rtsp_writer *writer, int fd, int status, const char *cseq,
                               const char *headers, const char *body) {
    __real_send_rtsp_response(writer, fd, status, cseq, headers, body);
    int armed = 1;
    if (status != 200 || headers == NULL || strstr(headers, "RTP-Info:") == NULL
        || !atomic_compare_exchange_strong(&hold_play, &armed, 2)) return;
    long long deadline = __real_c300x_monotonic_ms() + WAIT_MS;
    while (atomic_load(&hold_play) == 2 && __real_c300x_monotonic_ms() < deadline) usleep(5000);
}
static int ring_codes[64];
static int ring_code_count;

static void header(const char *message, const char *name, char *out, size_t out_len) {
    const char *line = strstr(message, name);
    out[0] = '\0';
    if (line == NULL) return;
    line += strlen(name);
    while (*line == ' ') line++;
    size_t length = strcspn(line, "\r\n");
    snprintf(out, out_len, "%.*s", (int)(length < out_len ? length : out_len - 1), line);
}

static void reply(int fd, const char *request, int code, const char *reason, const char *sdp) {
    char via[256], from[256], to[256], call_id[128], cseq[64], message[4096];
    header(request, "Via:", via, sizeof(via));
    header(request, "From:", from, sizeof(from));
    header(request, "To:", to, sizeof(to));
    header(request, "Call-ID:", call_id, sizeof(call_id));
    header(request, "CSeq:", cseq, sizeof(cseq));
    int length = snprintf(message, sizeof(message),
        "SIP/2.0 %d %s\r\nVia: %s\r\nFrom: %s\r\nTo: %s%s\r\nCall-ID: %s\r\nCSeq: %s\r\n"
        "Contact: <sip:c300x@127.0.0.1:41110;transport=tcp>\r\n%sContent-Length: %zu\r\n\r\n%s",
        code, reason, via, from, to, strstr(to, "tag=") ? "" : ";tag=station", call_id, cseq,
        sdp ? "Content-Type: application/sdp\r\n" : "", sdp ? strlen(sdp) : 0, sdp ? sdp : "");
    assert(c300x_media_sip_send_all(fd, message, (size_t)length) > 0);
}

#define TEST_KEY "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFB"
static const char station_sdp[] =
    "v=0\r\no=c300x 1 1 IN IP4 127.0.0.1\r\ns=-\r\nc=IN IP4 127.0.0.1\r\nt=0 0\r\n"
    "m=audio 7078 RTP/SAVP 0\r\na=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:" TEST_KEY "\r\n"
    "m=video 9078 RTP/SAVP 96\r\na=rtpmap:96 H264/90000\r\n"
    "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:" TEST_KEY "\r\n";

static void *station_connection(void *arg) {
    int fd = (int)(intptr_t)arg;
    char message[SIP_BUFFER_SIZE];
    bool ring = false;
    for (;;) {
        int n = c300x_media_sip_read_message(fd, message, sizeof(message), 30000);
        if (n <= 0) break;
        if (strncmp(message, "\r\n", 2) == 0) continue;
        if (strncmp(message, "REGISTER ", 9) == 0) {
            bool ring_register = strstr(message, "Call-ID: ha-ring-register") != NULL;
            if (ring_register) atomic_fetch_add(&ring_registers, 1);
            if (ring_register && atomic_exchange(&lose_ring_register, 0)) continue;
            if (ring_register && !ring) {
                ring = true;
                atomic_store(&ring_fd, fd);
            }
            reply(fd, message, 200, "Registration successful", NULL);
        } else if (strncmp(message, "INVITE ", 7) == 0) {
            char devaddr[32], entry[40];
            header(message, "a=DEVADDR:", devaddr, sizeof(devaddr));
            snprintf(entry, sizeof(entry), "I%s", devaddr);
            log_station(entry);
            atomic_fetch_add(&ondemand_invites, 1);
            if (atomic_exchange(&end_before_486, 0)) {
                bus("*8*3#1#4*411##");
                usleep(100000);
            }
            if (atomic_load(&station_busy)) reply(fd, message, 486, "Busy here", NULL);
            else reply(fd, message, 200, "Ok", station_sdp);
        } else if (strncmp(message, "BYE ", 4) == 0) {
            atomic_fetch_add(&station_byes, 1);
            reply(fd, message, 200, "Ok", NULL);
        } else if (strncmp(message, "SIP/2.0 ", 8) == 0 && ring) {
            pthread_mutex_lock(&codes_mutex);
            if (ring_code_count < 64) ring_codes[ring_code_count++] = c300x_media_sip_status_code(message);
            pthread_mutex_unlock(&codes_mutex);
        }
    }
    if (ring) atomic_store(&ring_fd, -1);
    close(fd);
    return NULL;
}

static void *station_accept(void *arg) {
    (void)arg;
    for (;;) {
        int fd = accept(sip_listen_fd, NULL, NULL);
        if (fd < 0) return NULL;
        pthread_t thread;
        assert(pthread_create(&thread, NULL, station_connection, (void *)(intptr_t)fd) == 0);
        pthread_detach(thread);
    }
}

static int ring_code_seen(int code) {
    int count = 0;
    pthread_mutex_lock(&codes_mutex);
    for (int i = 0; i < ring_code_count; i++) count += ring_codes[i] == code;
    pthread_mutex_unlock(&codes_mutex);
    return count;
}

static void wait_ring_code(int code, int nth) {
    long long deadline = __real_c300x_monotonic_ms() + WAIT_MS;
    while (ring_code_seen(code) < nth) {
        assert(__real_c300x_monotonic_ms() < deadline);
        usleep(5000);
    }
}

static void station_send(const char *method, int cseq, const char *body) {
    char message[4096];
    int fd = atomic_load(&ring_fd);
    assert(fd >= 0);
    int length = snprintf(message, sizeof(message),
        "%s sip:homeassistant@127.0.0.1:5060;transport=tcp SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:5060;branch=z9hG4bKring%d\r\n"
        "From: <sip:c300x@test.local>;tag=station-ring\r\nTo: <sip:alluser@test.local>\r\n"
        "Call-ID: ring-call-1\r\nCSeq: %d %s\r\nContact: <sip:c300x@127.0.0.1:41110;transport=tcp>\r\n"
        "%sContent-Length: %zu\r\n\r\n%s",
        method, cseq, cseq, method, body ? "Content-Type: application/sdp\r\n" : "",
        body ? strlen(body) : 0, body ? body : "");
    assert(c300x_media_sip_send_all(fd, message, (size_t)length) > 0);
}

void __real_c300x_video_bridge_station_busy(struct c300x_video *video);
void __wrap_c300x_video_bridge_station_busy(struct c300x_video *video) {
    __real_c300x_video_bridge_station_busy(video);
    if (atomic_exchange(&end_after_486, 0)) {
        bus("*8*3#1#4*411##");
        usleep(100000);
    }
}

/* ---- the agent's own event loop, as in the running agent ---- */

static struct agent_runtime *runtime;
static int udp_fd = -1;
static uint16_t udp_port;
static atomic_bool loop_stop;

static void *agent_loop(void *arg) {
    (void)arg;
    while (!atomic_load(&loop_stop)) {
        struct pollfd fds[2] = {{.fd = udp_fd, .events = POLLIN}};
        int video_count = c300x_video_pollfds(runtime->video, &fds[1], 1);
        int ready = poll(fds, (nfds_t)(1 + video_count), 20);
        c300x_call_hub_tick(&runtime->calls);
        if (ready <= 0) continue;
        if (fds[0].revents & POLLIN) handle_udp_event(udp_fd, runtime->config, runtime);
        if (video_count) c300x_video_handle_pollfds(runtime->video, &fds[1], video_count);
    }
    return NULL;
}

static void bus(const char *frame) {
    unsigned char payload[256] = {0};
    size_t length = 8 + 5 + 12;
    memcpy(payload + 8, "OPEN", 4);
    memcpy(payload + length, frame, strlen(frame));
    length += strlen(frame) + 1;
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(udp_port)};
    to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    assert(sendto(fd, payload, length, 0, (struct sockaddr *)&to, sizeof(to)) == (ssize_t)length);
    close(fd);
    usleep(30000);
}

/* ---- RTSP consumer (HA's go2rtc) ---- */

static uint16_t rtsp_port;

static int rtsp_request(int fd, const char *method, const char *path, const char *headers) {
    char message[1024], response[8192];
    static int cseq;
    int length = snprintf(message, sizeof(message), "%s rtsp://127.0.0.1:%u%s RTSP/1.0\r\nCSeq: %d\r\n%s\r\n",
                          method, rtsp_port, path, ++cseq, headers);
    if (c300x_media_sip_send_all(fd, message, (size_t)length) <= 0) return -1;
    size_t used = 0;
    for (;;) {
        ssize_t n = recv(fd, response + used, sizeof(response) - used - 1, 0);
        if (n <= 0) return -1;
        used += (size_t)n;
        response[used] = '\0';
        char *end = strstr(response, "\r\n\r\n");
        if (end && used >= (size_t)(end + 4 - response) + (size_t)c300x_media_sip_content_length(response)) break;
    }
    int status = 0;
    assert(sscanf(response, "RTSP/1.0 %d", &status) == 1);
    return status;
}

static int rtsp_open(void) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = htons(rtsp_port)};
    to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    long long deadline = __real_c300x_monotonic_ms() + WAIT_MS;
    while (connect(fd, (struct sockaddr *)&to, sizeof(to)) != 0) {
        assert(__real_c300x_monotonic_ms() < deadline);
        usleep(10000);
    }
    struct timeval timeout = {10, 0};
    assert(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
    return fd;
}

/* DESCRIBE, SETUP and PLAY; returns the PLAY status, -1 when the agent closed. */
static int rtsp_play(int fd, const char *path) {
    if (rtsp_request(fd, "DESCRIBE", path, "Accept: application/sdp\r\n") != 200) return -1;
    if (rtsp_request(fd, "SETUP", path, "Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n") != 200) return -1;
    return rtsp_request(fd, "PLAY", path, "Range: npt=0.000-\r\n");
}

static void status(struct c300x_video_status *out) { c300x_video_status(runtime->video, out); }

/* The agent drops a closed client when that client's thread reads the end
 * of its socket, which takes longer under load. A client opened before
 * then still meets the old one: another path or both slots taken, and the
 * answer is not the one the case is about. */
static void wait_clients(int count) {
    struct c300x_video_status current;
    long long deadline = __real_c300x_monotonic_ms() + WAIT_MS;
    for (;;) {
        status(&current);
        if (current.clients <= count) return;
        assert(__real_c300x_monotonic_ms() < deadline);
        usleep(5000);
    }
}

static void ring_starts(int *preview) {
    char ring_sdp[1024];
    snprintf(ring_sdp, sizeof(ring_sdp), "%s", station_sdp);
    bus("*8*1#1#4#21*11##");
    station_send("INVITE", 1, ring_sdp);
    wait_ring_code(183, 1);
    wait_event("doorbell.pressed", 1, NULL, 0);
    /* HA's ring preview pulls the stream while it rings. */
    *preview = rtsp_open();
    assert(rtsp_play(*preview, "/doorbell-video") == 200);
}

/* A Stream press: activate plus one go2rtc PLAY, both refused. */
static void stream_press_refused(const char *reason) {
    struct c300x_video_status current;
    assert(!c300x_video_activate(runtime->video, 1, NULL));
    status(&current);
    assert(strcmp(current.last_error, reason) == 0);
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 503);
    close(fd);
    wait_clients(0);
}

/* (a) Capture 13:37:27-13:38:35: the display answers, flexisip cancels the
 * agent's leg, the display call stays up until its 60 s limit. */
static void display_answer(bool end_frame_lost) {
    char data[4096];
    int preview;
    ring_starts(&preview);
    bus("*8*84*11##");
    bus("*8*85*11##");
    station_send("CANCEL", 1, NULL);
    wait_ring_code(200, 1);
    usleep(300000);
    bus("*8*2#1#4*11##");
    wait_event("doorbell.view_requested", 1, data, sizeof(data));
    assert(payload_external(data));
    /* The ring leg's close still reports the display's media. */
    wait_event("doorbell.media.closed", 1, data, sizeof(data));
    assert(payload_external(data));
    close(preview);
    wait_clients(0);
    struct c300x_video_status current;
    status(&current);
    assert(current.external_media_active);
    assert(strcmp(current.media_owner, "external_media") == 0);

    /* HA's Stream press during the display call. */
    assert(!c300x_video_activate(runtime->video, 1, NULL));
    status(&current);
    assert(strcmp(current.last_error, "external_session_active") == 0);
    assert(atomic_load(&ondemand_invites) == 0);
    /* go2rtc pulls the on-demand stream again and again (capture: ~80 tries). */
    for (int i = 0; i < 5; i++) {
        int fd = rtsp_open();
        assert(rtsp_play(fd, "/doorbell") == 503);
        close(fd);
        wait_clients(0);
    }
    assert(atomic_load(&ondemand_invites) == 0);
    status(&current);
    assert(current.external_media_active);

    /* bt_vct holds a display call for up to 60 s (TCONV): a press at
     * second 45 still meets the display call, not the station. */
    atomic_store(&clock_offset, 45000);
    stream_press_refused("external_session_active");
    status(&current);
    assert(current.external_media_active);
    assert(strcmp(current.media_owner, "external_media") == 0);
    assert(atomic_load(&ondemand_invites) == 0);

    if (end_frame_lost) {
        /* No end frame reached the agent: the guard runs out at 65 s and
         * the (free) station takes the next start. */
        atomic_store(&clock_offset, 66000);
        status(&current);
        assert(!current.external_media_active);
        assert(strcmp(current.media_owner, "idle") == 0);
        atomic_store(&station_busy, 0);
        assert(c300x_video_activate(runtime->video, 1, NULL));
        int fd = rtsp_open();
        assert(rtsp_play(fd, "/doorbell") == 200);
        assert(atomic_load(&ondemand_invites) == 1);
        close(fd);
        wait_clients(0);
        assert(count_events("doorbell.media.closed") == 1);
        return;
    }

    /* The display call ends at its 60 s limit. */
    atomic_store(&clock_offset, 60000);
    bus("*8*3#1#4*411##");
    wait_event("doorbell.media.closed", 2, data, sizeof(data));
    assert(!payload_external(data));
    usleep(300000);
    assert(count_events("doorbell.media.closed") == 2);
    status(&current);
    assert(!current.external_media_active);
    assert(strcmp(current.media_owner, "idle") == 0);
    assert(atomic_load(&ondemand_invites) == 0);
}

/* (b) Nobody answers: the station cancels at its timeout. */
static void unanswered(void) {
    char data[4096];
    int preview;
    ring_starts(&preview);
    station_send("CANCEL", 1, NULL);
    wait_ring_code(200, 1);
    wait_event("doorbell.media.closed", 1, data, sizeof(data));
    assert(!payload_external(data));
    close(preview);
    wait_clients(0);
    usleep(300000);
    assert(count_events("doorbell.media.closed") == 1);
    struct c300x_video_status current;
    status(&current);
    assert(!current.external_media_active && current.clients == 0);
    assert(strcmp(current.media_owner, "idle") == 0);
    assert(atomic_load(&ondemand_invites) == 0);
}

/* (c) HA answers: the station ends its display ring (bus *8*3), the call
 * goes on until the station's BYE. */
static void ha_answer(void) {
    char data[4096];
    int preview;
    ring_starts(&preview);
    assert(c300x_video_doorbell_call_answer(runtime->video));
    wait_ring_code(200, 1);
    wait_event("doorbell.view_requested", 1, data, sizeof(data));
    assert(!payload_external(data));
    bus("*8*3#1#4*411##");
    usleep(300000);
    assert(count_events("doorbell.media.closed") == 0);
    struct c300x_video_status current;
    status(&current);
    assert(current.ring_answered && strcmp(current.media_owner, "ring") == 0);
    station_send("BYE", 2, NULL);
    wait_event("doorbell.media.closed", 1, data, sizeof(data));
    assert(!payload_external(data));
    close(preview);
    wait_clients(0);
    usleep(300000);
    assert(count_events("doorbell.media.closed") == 1);
    status(&current);
    assert(strcmp(current.media_owner, "idle") == 0 && !current.external_media_active);
    assert(atomic_load(&ondemand_invites) == 0);
}

static void wait_invites(int count);
static void expect_log(const char *expected);

/* An API request to the call routes; returns the HTTP status. */
static int calls_api(const char *method, const char *path, const char *body, char *out, size_t out_len) {
    int fds[2];
    static struct request request;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, fds) == 0);
    memset(&request, 0, sizeof(request));
    snprintf(request.method, sizeof(request.method), "%s", method);
    snprintf(request.path, sizeof(request.path), "%s", path);
    snprintf(request.body, sizeof(request.body), "%s", body);
    request.body_len = strlen(request.body);
    struct c300x_call_routes routes = {&runtime->calls, &runtime->video_control, runtime->video, NULL};
    assert(c300x_http_calls_route(fds[0], &routes, &request));
    close(fds[0]);
    ssize_t n = recv(fds[1], out, out_len - 1, 0);
    close(fds[1]);
    assert(n > 0);
    out[n] = '\0';
    int code = 0;
    assert(sscanf(out, "HTTP/1.1 %d", &code) == 1);
    return code;
}

/* Two units ring within a second (frames of a three-unit installation):
 * the station has one ring session, so there is one call; each caller
 * frame names the unit of that call, the last one counts. */
static void two_units(void) {
    char data[4096], id[32], path[96];
    int preview;
    ring_starts(&preview);
    bus("*8*9#1#4*21##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    assert(strstr(data, "\"unit\":\"21\"") && strstr(data, "\"attribution\":\"caller_frame\""));
    sscanf(strstr(data, "\"call_id\":\"") + 11, "%31[^\"]", id);
    bus("*8*1#1#4#21*11##");
    bus("*8*9#1#4*22##");
    wait_event("call.caller_identified", 2, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"unit\":\"22\""));
    assert(count_events("doorbell.pressed") == 1);
    assert(count_events("outdoor_units.changed") == 2);

    assert(calls_api("POST", "/api/v1/calls/0badc0de-1/actions/answer", "", data, sizeof(data)) == 409);
    assert(strstr(data, "\"error\":\"call_not_current\"") && strstr(data, id));
    assert(calls_api("GET", "/api/v1/outdoor-units", "", data, sizeof(data)) == 200);
    assert(strstr(data, "\"id\":\"21\",\"where\":\"21\"") && strstr(data, "\"source\":\"seen\""));
    /* During a ring the ring's video is shown, whatever unit is asked. */
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{\"unit\":\"21\"}", data, sizeof(data)) == 200);
    assert(strstr(data, "\"ring_active\":true"));
    snprintf(path, sizeof(path), "{\"call_id\":\"%s\"}", id);
    assert(calls_api("POST", "/api/v1/outdoor-units/21/actions/unlock", path, data, sizeof(data)) == 409);

    bus("*8*19*22##");
    wait_event("door_unlock.started", 1, data, sizeof(data));
    assert(strstr(data, "\"unit\":\"22\"") && strstr(data, id));
    bus("*8*100#1#4*21##");
    usleep(100000);
    assert(count_events("call.ended") == 0);
    station_send("CANCEL", 1, NULL);
    wait_ring_code(200, 1);
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"reason\":\"media_closed\""));
    close(preview);
    assert(atomic_load(&ondemand_invites) == 0);
}

/* ---- the call lifecycle against captured sequences (1.7.19, one unit) ----
 * Start, answer and end come from the agent's ring and media events; the
 * caller and view frames only name the unit. *8*100 follows an answer or a
 * view start by 100-500 ms and ends nothing. */

static void current_call(char *id, size_t id_len) {
    char data[4096];
    assert(calls_api("GET", "/api/v1/calls", "", data, sizeof(data)) == 200);
    const char *at = strstr(data, "\"current_call_id\":");
    assert(at != NULL);
    at += strlen("\"current_call_id\":");
    id[0] = '\0';
    if (*at == '"') sscanf(at + 1, "%31[^\"]", id);
    (void)id_len;
}

static void assert_current(const char *expected) {
    char id[32];
    current_call(id, sizeof(id));
    if (strcmp(id, expected) != 0) {
        fprintf(stderr, "current call %s, expected %s\n", id, expected);
        abort();
    }
}

static void call_id_of(const char *data, char *id) {
    const char *at = strstr(data, "\"call_id\":\"");
    assert(at != NULL);
    sscanf(at + 11, "%31[^\"]", id);
}

static void ring_with_caller(char *id, int *preview) {
    char data[4096];
    ring_starts(preview);
    bus("*8*9#1#4*20##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    assert(strstr(data, "\"unit\":\"20\"") && strstr(data, "\"attribution\":\"caller_frame\""));
    call_id_of(data, id);
    assert_current(id);
}

static void call_api_action(const char *id, const char *action, int expected) {
    char path[96], data[4096];
    snprintf(path, sizeof(path), "/api/v1/calls/%s/actions/%s", id, action);
    int code = calls_api("POST", path, "", data, sizeof(data));
    if (code != expected) {
        fprintf(stderr, "%s: %d %s\n", path, code, data);
        abort();
    }
}

static void wait_byes(int count) {
    long long deadline = __real_c300x_monotonic_ms() + WAIT_MS;
    while (atomic_load(&station_byes) < count) {
        assert(__real_c300x_monotonic_ms() < deadline);
        usleep(5000);
    }
}

/* c300x-unanswered-ring-20260708-134502: nobody answers, no *8*100; the
 * station cancels after 29.9 s and the agent's media close ends the call. */
static void lifecycle_unanswered(void) {
    char data[4096], id[32];
    int preview;
    ring_with_caller(id, &preview);
    atomic_store(&clock_offset, 29600);
    assert_current(id);
    bus("*8*3#1#4*411##");
    station_send("CANCEL", 1, NULL);
    wait_ring_code(200, 1);
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"reason\":\"media_closed\""));
    close(preview);
    assert_current("");
    assert(count_events("call.answered") == 0);
}

/* c300x-ha-device-20260615-230207: HA answers after 13 s; *8*2, *8*3 and
 * *8*100 follow within 300 ms; HA hangs up 6.9 s later. */
static void lifecycle_ha_answer_ha_hangup(void) {
    char data[4096], id[32];
    int preview;
    ring_with_caller(id, &preview);
    atomic_store(&clock_offset, 13000);
    call_api_action(id, "answer", 200);
    wait_ring_code(200, 1);
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"ha\""));
    bus("*8*2#1#4*11##");
    bus("*8*3#1#4*411##");
    bus("*8*100#1#4*20##");
    bus("*8*2#1#4*11##");
    bus("*8*100#1#4*20##");
    usleep(300000);
    assert(count_events("call.ended") == 0 && count_events("call.answered") == 1);
    assert_current(id);
    atomic_store(&clock_offset, 19900);
    call_api_action(id, "hangup", 200);
    wait_byes(1);
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"reason\":\"hangup\""));
    close(preview);
    assert_current("");
}

/* Capture 13:37:27-13:38:35: the display answers; the agent's ring leg is
 * cancelled while the display call goes on until its end frame. */
static void lifecycle_station_answer_station_hangup(void) {
    char data[4096], id[32], path[96];
    int preview;
    ring_with_caller(id, &preview);
    bus("*8*84*11##");
    bus("*8*85*11##");
    station_send("CANCEL", 1, NULL);
    wait_ring_code(200, 1);
    usleep(300000);
    bus("*8*2#1#4*11##");
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"station\""));
    wait_event("doorbell.media.closed", 1, data, sizeof(data));
    assert(payload_external(data));
    snprintf(path, sizeof(path), "{\"kind\":\"ring\",\"call_id\":\"%s\",", id);
    assert(strncmp(data, path, strlen(path)) == 0);
    close(preview);
    bus("*8*100#1#4*20##");
    usleep(300000);
    assert(count_events("call.ended") == 0);
    assert_current(id);
    atomic_store(&clock_offset, 60000);
    bus("*8*3#1#4*411##");
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"reason\":\"media_closed\""));
    assert_current("");
    assert(atomic_load(&station_byes) == 0);
    /* The display call's bus end frame is the ring's close. */
    wait_event("doorbell.media.closed", 2, data, sizeof(data));
    snprintf(path, sizeof(path), "{\"raw\":\"*8*3#1#4*411##\",\"kind\":\"ring\",\"call_id\":\"%s\",", id);
    assert(strncmp(data, path, strlen(path)) == 0);
}

/* c300x-ha-device-20260616-000849: HA answers; 60 s later the station ends
 * the call (*8*3, then its BYE). */
static void lifecycle_ha_answer_station_hangup(void) {
    char data[4096], id[32];
    int preview;
    ring_with_caller(id, &preview);
    atomic_store(&clock_offset, 17100);
    call_api_action(id, "answer", 200);
    wait_ring_code(200, 1);
    bus("*8*2#1#4*11##");
    bus("*8*3#1#4*411##");
    bus("*8*100#1#4*20##");
    usleep(300000);
    assert_current(id);
    atomic_store(&clock_offset, 77400);
    bus("*8*3#1#4*411##");
    usleep(300000);
    assert_current(id);
    station_send("BYE", 2, NULL);
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"reason\":\"media_closed\""));
    close(preview);
    assert_current("");
    assert(atomic_load(&station_byes) == 0);
}

/* c300x-ha-first-click-click-stop-20260621-214931: HA's on-demand view of
 * the default unit; *8*100#5 follows 578 ms later; HA stops 2.1 s later. */
static void lifecycle_ondemand_view(void) {
    char data[4096], id[32];
    atomic_store(&station_busy, 0);
    assert(c300x_video_activate(runtime->video, 1, NULL));
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    bus("*8*1#5#4#20*11##");
    wait_event("call.view_started", 1, data, sizeof(data));
    assert(strstr(data, "\"unit\":\"20\""));
    call_id_of(data, id);
    bus("*8*9#5#4*20##");
    bus("*8*2#5#4*11##");
    bus("*8*3#5#4*411##");
    bus("*8*100#5#4*20##");
    usleep(300000);
    assert(count_events("call.ended") == 0 && count_events("call.answered") == 0);
    assert(calls_api("GET", "/api/v1/calls", "", data, sizeof(data)) == 200);
    assert(strstr(data, "\"state\":\"viewing\""));
    assert_current(id);
    /* Stopped elsewhere (HA's stop button): the view's media closes. */
    c300x_video_stop(runtime->video);
    wait_byes(1);
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"kind\":\"view\",\"reason\":\"media_closed\""));
    close(fd);
    assert_current("");
}

/* A ring with no RTSP client on the ring preview. */
static void ring_without_preview(char *id, int nth) {
    char data[4096];
    bus("*8*1#1#4#21*11##");
    station_send("INVITE", nth, station_sdp);
    wait_ring_code(183, nth);
    wait_event("doorbell.pressed", nth, data, sizeof(data));
    call_id_of(data, id);
}

/* The display answers while no preview client holds the ring leg: the
 * leg's close comes before the answer frame. */
static void display_answer_without_preview(void) {
    char data[4096], id[32];
    ring_without_preview(id, 1);
    bus("*8*9#1#4*20##");
    wait_event("call.caller_identified", 1, NULL, 0);
    station_send("CANCEL", 1, NULL);
    wait_ring_code(200, 1);
    wait_event("doorbell.media.closed", 1, data, sizeof(data));
    assert(!payload_external(data));
    usleep(300000);
    bus("*8*2#1#4*11##");
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"station\""));
    usleep(2000000);
    assert(count_events("call.ended") == 0);
    assert_current(id);
    atomic_store(&clock_offset, 60000);
    bus("*8*3#1#4*411##");
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"reason\":\"media_closed\""));
    assert_current("");
}

/* c300x-app-device-20260612-182122: the app answers; the station's end
 * frame of the ring comes before the answer frame. */
static void app_answer_end_frame_first(void) {
    char data[4096], id[32];
    int preview;
    ring_with_caller(id, &preview);
    bus("*8*3#1#4*411##");
    bus("*8*2#1#4*11##");
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"station\""));
    station_send("CANCEL", 1, NULL);
    wait_ring_code(200, 1);
    close(preview);
    usleep(2000000);
    assert(count_events("call.ended") == 0);
    assert_current(id);
    /* No end frame reaches the agent: the display call's 60 s limit and
     * the agent's guard end the call. */
    atomic_store(&clock_offset, 66000);
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"reason\":\"media_closed\""));
    assert_current("");
}

/* The display answers and its end frame is lost: after the agent's 65 s
 * display guard the call is over and HA can answer the next ring. */
static void display_answer_end_lost_call(void) {
    char data[4096], id[32], next[32];
    int preview;
    ring_with_caller(id, &preview);
    bus("*8*84*11##");
    bus("*8*85*11##");
    station_send("CANCEL", 1, NULL);
    wait_ring_code(200, 1);
    usleep(300000);
    bus("*8*2#1#4*11##");
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, "\"answered_by\":\"station\""));
    wait_event("doorbell.media.closed", 1, data, sizeof(data));
    assert(payload_external(data));
    close(preview);
    usleep(300000);
    assert(count_events("call.ended") == 0);
    atomic_store(&clock_offset, 66000);
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"reason\":\"media_closed\""));
    assert_current("");
    ring_without_preview(next, 2);
    assert(strcmp(next, id) != 0);
    assert_current(next);
    call_api_action(next, "answer", 200);
    wait_event("call.answered", 2, data, sizeof(data));
    assert(strstr(data, next) && strstr(data, "\"answered_by\":\"ha\""));
}

/* c300x-ring-answer-20260703-185353: HA answers at +277 ms, the caller
 * frame comes at +302 ms; c300x-ha-device-20260615-232132: ring copies at
 * +546 and +553 ms. One call, and it gets the caller's unit. */
static void answer_before_caller(void) {
    char data[4096], id[32];
    int preview;
    ring_starts(&preview);
    wait_event("doorbell.pressed", 1, data, sizeof(data));
    call_id_of(data, id);
    call_api_action(id, "answer", 200);
    wait_ring_code(200, 1);
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"ha\""));
    bus("*8*9#1#4*20##");
    bus("*8*1#1#4#21*11##");
    bus("*8*1#1#4#21*11##");
    bus("*8*9#1#4*20##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"unit\":\"20\"") && strstr(data, "\"attribution\":\"caller_frame\""));
    usleep(1300000);
    assert(count_events("doorbell.pressed") == 1);
    assert(count_events("call.caller_identified") == 1);
    assert(calls_api("GET", "/api/v1/calls", "", data, sizeof(data)) == 200);
    assert(strstr(data, "-2\"") == NULL);
    assert_current(id);
    close(preview);
}

/* HA's answer waits for the media worker and its caller leaves before it
 * runs; the display then answers: that answer is the station's. */
static void abandoned_answer_then_station(void) {
    static struct c300x_request_queue queue;
    static struct request request;
    char data[4096], id[32];
    int preview, fds[2];
    ring_with_caller(id, &preview);
    assert(c300x_video_control_init(&runtime->video_control, &queue));
    runtime->video_control.worker.owner_fd = 4242;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, fds) == 0);
    memset(&request, 0, sizeof(request));
    snprintf(request.method, sizeof(request.method), "POST");
    snprintf(request.path, sizeof(request.path), "/api/v1/calls/%s/actions/answer", id);
    struct c300x_call_routes routes = {&runtime->calls, &runtime->video_control, runtime->video, NULL};
    c300x_video_control_begin(&runtime->video_control, fds[0]);
    assert(c300x_http_calls_route(fds[0], &routes, &request));
    assert(c300x_video_control_deferred(&runtime->video_control));
    c300x_video_control_end(&runtime->video_control, 1);
    c300x_video_control_abandon(&runtime->video_control, fds[0]);
    close(fds[0]);
    close(fds[1]);
    runtime->video_control.worker.owner_fd = C300X_REQUEST_WORKER_FREE;
    runtime->video_control.worker.armed_fd = -1;
    bus("*8*84*11##");
    bus("*8*85*11##");
    station_send("CANCEL", 1, NULL);
    wait_ring_code(200, 1);
    usleep(300000);
    bus("*8*2#1#4*11##");
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"station\""));
    close(preview);
}

/* HA's on-demand view is the current call; the card ends it with the
 * call's hang-up. */
static void view_is_current(void) {
    char data[4096], id[32];
    atomic_store(&station_busy, 0);
    assert(c300x_video_activate(runtime->video, 1, NULL));
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    bus("*8*1#5#4#20*11##");
    wait_event("call.view_started", 1, data, sizeof(data));
    call_id_of(data, id);
    assert(calls_api("GET", "/api/v1/calls", "", data, sizeof(data)) == 200);
    assert(strstr(data, "\"state\":\"viewing\""));
    assert_current(id);
    call_api_action(id, "hangup", 200);
    wait_byes(1);
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"kind\":\"view\",\"reason\":\"hangup\""));
    close(fd);
    assert_current("");
}

/* HA's answer is refused (the agent has no ring leg: only the bus rang);
 * the display then answers: that answer is the station's, not HA's. */
static void refused_answer_then_station(void) {
    char data[4096], id[32];
    bus("*8*1#1#4#21*11##");
    wait_event("doorbell.pressed", 1, NULL, 0);
    bus("*8*9#1#4*20##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    call_id_of(data, id);
    call_api_action(id, "answer", 409);
    bus("*8*2#1#4*11##");
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"station\""));
}

/* Smartphone forwarding on or blocked: only the bus rings, the agent has no
 * ring leg. HA's live view during the ring answers nothing: the station
 * still rings. The agent's answer of its own ring leg is HA's. */
static void view_during_bus_ring(void) {
    char data[4096], id[32];
    atomic_store(&station_busy, 0);
    bus("*8*1#1#4#21*11##");
    bus("*8*9#1#4*20##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    call_id_of(data, id);
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{}", data, sizeof(data)) == 200);
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    wait_event("doorbell.view_requested", 1, data, sizeof(data));
    assert(strstr(data, "\"media\"") == NULL);
    usleep(300000);
    assert(count_events("call.answered") == 0);
    assert(calls_api("GET", "/api/v1/calls", "", data, sizeof(data)) == 200);
    assert(strstr(data, "\"kind\":\"ring\",\"state\":\"ringing\""));
    assert_current(id);
    c300x_video_stop(runtime->video);
    wait_byes(1);
    close(fd);
}

/* Only the bus rings, HA opens the live view of the ringing unit: the
 * station reports that view as every on-demand view in the captures
 * (c300x-app-ondemand-20260613-124656, c300x-ha-card-2click-ondemand-
 * 20260621-181353): view frame, 3, *8*2#5#, then 6. That 6 answers no
 * ring; the display's answer frame still does. */
static void view_state6_during_bus_ring(void) {
    char data[4096], id[32];
    atomic_store(&station_busy, 0);
    bus("*8*1#1#4#21*11##");
    bus("*#8**35*1*0*0##");
    bus("*8*9#1#4*21##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    call_id_of(data, id);
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{}", data, sizeof(data)) == 200);
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    wait_event("doorbell.view_requested", 1, NULL, 0);
    bus("*8*1#5#4#21*11##");
    bus("*#8**35*3*0*0##");
    bus("*8*2#5#4*11##");
    bus("*#8**35*6*0*0##");
    wait_event("station.call_state", 3, data, sizeof(data));
    assert(strstr(data, "\"code\":6"));
    usleep(300000);
    assert(count_events("call.answered") == 0);
    assert(calls_api("GET", "/api/v1/calls", "", data, sizeof(data)) == 200);
    assert(strstr(data, "\"kind\":\"ring\",\"state\":\"ringing\""));
    assert_current(id);
    /* After the view's start transition (3.5 s), in which an answer frame is
     * taken for the view's own. */
    atomic_store(&clock_offset, 4000);
    bus("*8*2#1#4*11##");
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"station\""));
    c300x_video_stop(runtime->video);
    wait_byes(1);
    close(fd);
}

/* HA views, a visitor rings (bus only), HA stops its view: the view call
 * ends, the ring call rings on until its own end (here the station's idle). */
static void view_close_keeps_ring(void) {
    char data[4096], id[32], view[32], fields[96];
    atomic_store(&station_busy, 0);
    assert(c300x_video_activate(runtime->video, 1, NULL));
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    bus("*8*1#5#4#20*11##");
    wait_event("call.view_started", 1, data, sizeof(data));
    call_id_of(data, view);
    bus("*8*1#1#4#21*11##");
    bus("*8*9#1#4*21##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    call_id_of(data, id);
    c300x_video_stop(runtime->video);
    wait_byes(1);
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, "\"kind\":\"view\"") && strstr(data, id) == NULL);
    /* The close names its media and its call: the view's, not the ring's. */
    wait_event("doorbell.media.closed", 1, data, sizeof(data));
    snprintf(fields, sizeof(fields), "{\"kind\":\"view\",\"call_id\":\"%s\",", view);
    assert(strstr(data, "\"media\"") == NULL && strncmp(data, fields, strlen(fields)) == 0);
    usleep(2000000);
    assert(count_events("call.ended") == 1 && count_events("call.answered") == 0);
    assert_current(id);
    bus("*#8**35*0*0*0##");
    wait_event("call.ended", 2, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"reason\":\"station_idle\""));
    close(fd);
}

/* The display views unit 20, unit 21 rings: the display's view end ends
 * the view call only. */
static void display_view_end_keeps_ring(void) {
    char data[4096], id[32];
    bus("*8*1#5#4#20*11##");
    wait_event("call.view_started", 1, NULL, 0);
    bus("*8*1#1#4#21*11##");
    bus("*8*9#1#4*21##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    call_id_of(data, id);
    bus("*8*3#5#4*411##");
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, "\"unit\":\"20\",\"kind\":\"view\""));
    usleep(2000000);
    assert(count_events("call.ended") == 1 && count_events("call.answered") == 0);
    assert_current(id);
}

/* The display views unit 20, unit 21 rings (bus only), the view ends,
 * then the ring ends unanswered with its bus end frame. The agent has no
 * media of that ring, so the frame is no media close and ends nothing; the
 * station's idle ends the ring call. */
static void unanswered_bus_ring_end_frame(void) {
    char data[4096], id[32];
    bus("*8*1#5#4#20*11##");
    wait_event("call.view_started", 1, NULL, 0);
    bus("*8*1#1#4#21*11##");
    bus("*8*9#1#4*21##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    call_id_of(data, id);
    bus("*8*3#5#4*411##");
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, "\"kind\":\"view\""));
    bus("*8*3#1#4*411##");
    usleep(2000000);
    assert(count_events("doorbell.media.closed") == 1 && count_events("call.ended") == 1);
    assert_current(id);
    bus("*#8**35*0*0*0##");
    wait_event("call.ended", 2, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"reason\":\"station_idle\""));
    assert_current("");
}

/* The display views unit 20: the agent cannot end that view. HA's hang-up
 * is refused (409 station_busy), nothing reaches the station, the view
 * call goes on. HA's own view still ends with its hang-up (view_is_current). */
static void display_view_hangup(void) {
    char data[4096], id[32], path[96];
    struct c300x_video_status current;
    bus("*8*1#5#4#20*11##");
    wait_event("call.view_started", 1, data, sizeof(data));
    call_id_of(data, id);
    snprintf(path, sizeof(path), "/api/v1/calls/%s/actions/hangup", id);
    assert(calls_api("POST", path, "", data, sizeof(data)) == 409);
    assert(strstr(data, "{\"ok\":false,\"error\":\"station_busy\"}"));
    usleep(300000);
    assert(count_events("call.ended") == 0 && count_events("doorbell.media.closed") == 0);
    assert_current(id);
    status(&current);
    assert(current.external_media_active);
    assert(atomic_load(&station_byes) == 0);
}

/* The display answers the ring (the agent's leg is cancelled): the agent
 * holds no leg of the call. HA's hang-up is refused (409 station_busy),
 * nothing reaches the station, the call goes on until the display ends it. */
static void display_answered_hangup(void) {
    char data[4096], id[32], path[96];
    int preview;
    ring_starts(&preview);
    bus("*8*9#1#4*21##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    call_id_of(data, id);
    assert(calls_api("GET", "/api/v1/calls", "", data, sizeof(data)) == 200);
    assert(strstr(data, "\"state\":\"ringing\"") && strstr(data, "\"can_hangup\":true}"));
    bus("*8*84*11##");
    bus("*8*85*11##");
    station_send("CANCEL", 1, NULL);
    wait_ring_code(200, 1);
    usleep(300000);
    bus("*8*2#1#4*11##");
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"station\""));
    close(preview);
    wait_clients(0);
    assert(calls_api("GET", "/api/v1/calls", "", data, sizeof(data)) == 200);
    assert(strstr(data, "\"state\":\"answered\"") && strstr(data, "\"can_hangup\":false}"));
    snprintf(path, sizeof(path), "/api/v1/calls/%s/actions/hangup", id);
    assert(calls_api("POST", path, "", data, sizeof(data)) == 409);
    assert(strstr(data, "{\"ok\":false,\"error\":\"station_busy\"}"));
    usleep(300000);
    assert(count_events("call.ended") == 0 && atomic_load(&station_byes) == 0);
    assert_current(id);
    atomic_store(&clock_offset, 60000);
    bus("*8*3#1#4*411##");
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"reason\":\"media_closed\""));
}

/* Only the bus rings (no ring leg of the agent) while HA's live view runs:
 * HA's hang-up of the ring call is refused (409 ring_call_not_active) and
 * stops nothing, the view neither; the ring call stays current, the
 * display still answers it. */
static void bus_ring_hangup_during_view(void) {
    char data[4096], id[32], path[96];
    struct c300x_video_status current;
    atomic_store(&station_busy, 0);
    bus("*8*1#1#4#21*11##");
    bus("*8*9#1#4*21##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    call_id_of(data, id);
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{}", data, sizeof(data)) == 200);
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    wait_event("doorbell.view_requested", 1, NULL, 0);
    assert(calls_api("GET", "/api/v1/calls", "", data, sizeof(data)) == 200);
    assert(strstr(data, "\"kind\":\"ring\",\"state\":\"ringing\"") && strstr(data, "\"can_hangup\":false}"));
    snprintf(path, sizeof(path), "/api/v1/calls/%s/actions/hangup", id);
    assert(calls_api("POST", path, "", data, sizeof(data)) == 409);
    assert(strstr(data, "{\"ok\":false,\"error\":\"ring_call_not_active\"}"));
    /* The media layer's ring hang-up stops no view either. */
    c300x_video_doorbell_call_hangup(runtime->video);
    usleep(300000);
    status(&current);
    assert(current.call_active && current.clients == 1);
    assert(atomic_load(&station_byes) == 0);
    assert(count_events("call.ended") == 0 && count_events("doorbell.media.closed") == 0);
    assert_current(id);
    /* After the view's start transition (3.5 s), in which an answer frame is
     * taken for the view's own. */
    atomic_store(&clock_offset, 4000);
    bus("*8*2#1#4*11##");
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"station\""));
    c300x_video_stop(runtime->video);
    wait_byes(1);
    close(fd);
}

static void agent_answer_is_ha(void) {
    char data[4096], id[32];
    int preview;
    ring_with_caller(id, &preview);
    assert(c300x_video_doorbell_call_answer(runtime->video));
    wait_ring_code(200, 1);
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"ha\""));
    wait_event("doorbell.view_requested", 1, data, sizeof(data));
    assert(strstr(data, "\"media\"") == NULL && strstr(data, id));
    close(preview);
}

/* The agent's own event of its ring leg's answer is Home Assistant's
 * answer by itself, also when the leg's answer state is gone by the time
 * the event is read: here no ring leg reports one. */
static void own_ring_answer_is_ha(void) {
    char data[4096], id[32];
    struct c300x_video_status current;
    bus("*8*1#1#4#21*11##");
    bus("*8*9#1#4*21##");
    wait_event("call.caller_identified", 1, data, sizeof(data));
    call_id_of(data, id);
    status(&current);
    assert(!current.ring_answered && !current.ring_answer_requested);
    dispatch_video_event(runtime, "doorbell.view_requested", C300X_VIDEO_EVENT_RING, 0);
    wait_event("call.answered", 1, data, sizeof(data));
    assert(strstr(data, id) && strstr(data, "\"answered_by\":\"ha\""));
}

/* A bus ring without the agent's ring leg: until the caller frame names
 * its unit, video of the current call has none (409 call_unit_pending, no
 * view of the default unit); then the view is the caller's. */
static void pending_unit_video(void) {
    char data[4096];
    atomic_store(&station_busy, 0);
    bus("*8*1#1#4#21*11##");
    wait_event("doorbell.pressed", 1, NULL, 0);
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{}", data, sizeof(data)) == 409);
    assert(strstr(data, "\"error\":\"call_unit_pending\"") && strstr(data, "\"retry_after_ms\":"));
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{\"unit\":\"current\"}", data,
                     sizeof(data)) == 409);
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{\"unit\":\"20\"}", data,
                     sizeof(data)) == 200);
    bus("*8*9#1#4*21##");
    wait_event("call.caller_identified", 1, NULL, 0);
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{}", data, sizeof(data)) == 200);
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    wait_invites(1);
    expect_log("I21");
    c300x_video_stop(runtime->video);
    wait_byes(1);
    close(fd);
}

/* Call ids up to 32 characters are well formed: an unknown one is not
 * current (409); only an empty or longer one is a bad request (400). */
static void call_id_lengths(void) {
    char data[4096], id[40], path[128], body[96];
    for (size_t length = 23; length <= 33; length++) {
        memset(id, 'a', length);
        id[length] = '\0';
        int expected = length <= 32 ? 409 : 400;
        snprintf(path, sizeof(path), "/api/v1/calls/%s/actions/hangup", id);
        assert(calls_api("POST", path, "", data, sizeof(data)) == expected);
        snprintf(path, sizeof(path), "/api/v1/calls/%s/actions/answer", id);
        assert(calls_api("POST", path, "", data, sizeof(data)) == expected);
        snprintf(body, sizeof(body), "{\"call_id\":\"%s\"}", id);
        assert(calls_api("POST", "/api/v1/outdoor-units/20/actions/unlock", body, data, sizeof(data)) == expected);
        assert(strstr(data, expected == 409 ? "call_not_current" : "invalid_call_id"));
    }
}

/* The boot id exists from the start: before the first call a restart of
 * the agent already shows as a new boot id. */
static void boot_id_at_start(void) {
    char data[4096], boot[16] = "", id[32];
    int preview;
    assert(calls_api("GET", "/api/v1/calls", "", data, sizeof(data)) == 200);
    assert(sscanf(strstr(data, "\"boot_id\":\"") + 11, "%15[0-9a-f]", boot) == 1 && strlen(boot) == 8);
    ring_with_caller(id, &preview);
    assert(strncmp(id, boot, 8) == 0 && id[8] == '-');
    close(preview);
}


/* ---- one ring of a one-unit station, as 3.0.0 reports it ---- */
static void strip_key(char *data, const char *key) {
    char pattern[32];
    snprintf(pattern, sizeof(pattern), "\"%s\":", key);
    char *at;
    while ((at = strstr(data, pattern)) != NULL) {
        char *value = at + strlen(pattern);
        char *end = value;
        if (*value == '"') { end = strchr(value + 1, '"'); end = end ? end + 1 : value; }
        else while (*end && *end != ',' && *end != '}') end++;
        if (at[-1] == ',') at--;
        else if (*end == ',') end++;
        memmove(at, end, strlen(end) + 1);
    }
}

static void single_unit_as_3_0_0(void) {
    int preview;
    ring_starts(&preview);
    bus("*8*1#1#4#21*11##");
    bus("*8*9#1#4*20##");
    assert(c300x_video_doorbell_call_answer(runtime->video));
    wait_ring_code(200, 1);
    wait_event("doorbell.view_requested", 1, NULL, 0);
    bus("*8*2#1#4*11##");
    bus("*8*3#1#4*411##");
    bus("*8*100#1#4*20##");
    bus("*8*19*20##");
    bus("*8*20*20##");
    usleep(300000);
    station_send("BYE", 2, NULL);
    wait_event("doorbell.media.closed", 1, NULL, 0);
    close(preview);
    usleep(300000);
    pthread_mutex_lock(&events_mutex);
    for (int i = 0; i < event_total; i++) {
        if (strncmp(event_types[i], "call.", 5) == 0 || strncmp(event_types[i], "outdoor_units.", 14) == 0) continue;
        char data[4096];
        snprintf(data, sizeof(data), "%s", event_data[i]);
        strip_key(data, "call_id");
        strip_key(data, "unit");
        strip_key(data, "attribution");
        strip_key(data, "kind");
        printf("event %s %s\n", event_types[i], data);
    }
    pthread_mutex_unlock(&events_mutex);
}

/* (d) The station answers 486 Busy with no external marker (here: no bus
 * frame announced the call). One INVITE, then no SIP until it is free. */
static void station_busy_case(bool freed_by_bus) {
    struct c300x_video_status current;
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 500);
    close(fd);
    wait_clients(0);
    assert(atomic_load(&ondemand_invites) == 1);
    status(&current);
    assert(strcmp(current.last_error, "ondemand_sip_setup_failed:answer_486") == 0);
    for (int i = 0; i < 5; i++) {
        fd = rtsp_open();
        assert(rtsp_play(fd, "/doorbell") == 503);
        close(fd);
        wait_clients(0);
    }
    assert(!c300x_video_activate(runtime->video, 1, NULL));
    status(&current);
    assert(strcmp(current.last_error, "station_busy") == 0);
    assert(!current.external_media_active && strcmp(current.media_owner, "idle") == 0);
    assert(atomic_load(&ondemand_invites) == 1);
    /* Still inside the longest display call the 486 may stand for. */
    atomic_store(&clock_offset, 45000);
    stream_press_refused("station_busy");
    assert(atomic_load(&ondemand_invites) == 1);

    atomic_store(&station_busy, 0);
    if (freed_by_bus) {
        bus("*8*3#1#4*411##");
    } else {
        atomic_store(&clock_offset, 66000);
    }
    assert(c300x_video_activate(runtime->video, 1, NULL));
    fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    assert(atomic_load(&ondemand_invites) == 2);
    status(&current);
    assert(strcmp(current.media_owner, "agent") == 0);
    close(fd);
    wait_clients(0);
}

/* (e) The call the station was busy with ends while the failed start still
 * counts as starting: its end frame is filtered as a start transition, yet
 * the station is free, so the next start calls it at once. */
static void station_freed_during_start(bool before_486) {
    struct c300x_video_status current;
    atomic_store(before_486 ? &end_before_486 : &end_after_486, 1);
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 500);
    close(fd);
    wait_clients(0);
    assert(atomic_load(&ondemand_invites) == 1);
    assert(!atomic_load(&end_before_486) && !atomic_load(&end_after_486));
    usleep(100000);
    assert(count_events("doorbell.media.closed") == 0);
    atomic_store(&station_busy, 0);
    assert(c300x_video_activate(runtime->video, 1, NULL));
    fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    assert(atomic_load(&ondemand_invites) == 2);
    status(&current);
    assert(strcmp(current.media_owner, "agent") == 0);
    close(fd);
    wait_clients(0);
}

static uint16_t bound_port(int fd) {
    struct sockaddr_in address;
    socklen_t length = sizeof(address);
    assert(getsockname(fd, (struct sockaddr *)&address, &length) == 0);
    return ntohs(address.sin_port);
}

static void wait_invites(int count) {
    long long deadline = __real_c300x_monotonic_ms() + WAIT_MS;
    while (atomic_load(&ondemand_invites) < count) {
        assert(__real_c300x_monotonic_ms() < deadline);
        usleep(5000);
    }
}

/* Between two INVITEs only the count of BYEs and cache drops is compared ("B G"). */
static void expect_log(const char *expected) {
    char seen[sizeof(station_log)], *save = NULL;
    size_t used = 0;
    int byes = 0, drops = 0;
    pthread_mutex_lock(&codes_mutex);
    char copy[sizeof(station_log)];
    snprintf(copy, sizeof(copy), "%s", station_log);
    pthread_mutex_unlock(&codes_mutex);
    seen[0] = '\0';
    for (char *token = strtok_r(copy, " ", &save);; token = strtok_r(NULL, " ", &save)) {
        if (token == NULL || token[0] == 'I') {
            for (; byes > 0; byes--) used += (size_t)snprintf(seen + used, sizeof(seen) - used, "%sB", used ? " " : "");
            for (; drops > 0; drops--) used += (size_t)snprintf(seen + used, sizeof(seen) - used, "%sG", used ? " " : "");
            if (token == NULL) break;
            used += (size_t)snprintf(seen + used, sizeof(seen) - used, "%s%s", used ? " " : "", token);
        } else if (token[0] == 'B') {
            byes++;
        } else {
            drops++;
        }
    }
    if (strcmp(seen, expected) != 0) fprintf(stderr, "station saw \"%s\", expected \"%s\"\n", seen, expected);
    assert(strcmp(seen, expected) == 0);
}

/* On-demand views of several units (three-unit installation: 20#2 behind
 * an apartment interface, 21, 22). Each INVITE names its unit in
 * a=DEVADDR, verbatim; a view of another unit ends the running one first
 * (BYE, its cached frames dropped), then the parked client gets the new
 * unit's view. The view frame names the unit of the view call. */
static void ondemand_units(void) {
    char data[4096];
    atomic_store(&station_busy, 0);
    assert(c300x_media_devaddr_valid("21") && c300x_media_devaddr_valid("20#2") && c300x_media_devaddr_valid("29#15"));
    assert(!c300x_media_devaddr_valid("11") && !c300x_media_devaddr_valid("31#2"));
    assert(!c300x_media_devaddr_valid("") && !c300x_media_devaddr_valid(NULL) && !c300x_media_devaddr_valid("2a"));
    /* The station's rule: the unit's address after the leading 2 is below
     * 96 (210: unit 10, 295: unit 95); a 2 alone names no unit. */
    assert(c300x_media_devaddr_valid("210") && c300x_media_devaddr_valid("295") && c300x_media_devaddr_valid("295#1"));
    assert(!c300x_media_devaddr_valid("296") && !c300x_media_devaddr_valid("2") && !c300x_media_devaddr_valid("2#1"));

    /* The default unit, as before: the configured DEVADDR. */
    assert(c300x_video_activate(runtime->video, 1, NULL));
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    wait_invites(1);
    expect_log("I20");

    /* Another unit: the running view ends before its INVITE. */
    assert(c300x_video_activate(runtime->video, 1, "21"));
    wait_invites(2);
    expect_log("I20 B G I21");
    bus("*8*1#5#4#21*11##");
    wait_event("call.view_started", 1, data, sizeof(data));
    assert(strstr(data, "\"unit\":\"21\""));

    /* The same unit again, through the route: the view goes on. */
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{\"unit\":\"21\"}", data, sizeof(data)) == 200);
    usleep(300000);
    expect_log("I20 B G I21");

    /* A unit behind an apartment interface: its full address. */
    assert(c300x_video_activate(runtime->video, 1, "20#2"));
    wait_invites(3);
    expect_log("I20 B G I21 B G I20#2");
    wait_event("call.ended", 1, data, sizeof(data));
    assert(strstr(data, "\"kind\":\"view\",\"reason\":\"media_closed\""));

    /* Back to the default unit through the route, without a unit. */
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{}", data, sizeof(data)) == 200);
    wait_invites(4);
    expect_log("I20 B G I21 B G I20#2 B G I20");
    c300x_video_stop(runtime->video);
    wait_byes(4);
    close(fd);
}

/* During a view of 21 a unit the station cannot view (31) is refused, as
 * without a view: the view of 21 goes on, no view of the default unit. */
static void unviewable_unit_during_view(void) {
    char data[4096];
    atomic_store(&station_busy, 0);
    bus("*8*66*21##");
    bus("*8*66*31##");
    wait_event("door.opened", 2, NULL, 0);
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{\"unit\":\"31\"}", data,
                     sizeof(data)) == 409);
    assert(strstr(data, "\"error\":\"unit_video_unsupported\""));
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{\"unit\":\"21\"}", data,
                     sizeof(data)) == 200);
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    wait_invites(1);
    bus("*8*1#5#4#21*11##");
    wait_event("call.view_started", 1, data, sizeof(data));
    assert(strstr(data, "\"unit\":\"21\""));
    assert(calls_api("POST", "/api/v1/video/doorbell/actions/activate", "{\"unit\":\"31\"}", data,
                     sizeof(data)) == 409);
    assert(strstr(data, "\"error\":\"unit_video_unsupported\""));
    usleep(300000);
    expect_log("I21");
    assert(count_events("call.ended") == 0);
    c300x_video_stop(runtime->video);
    wait_byes(1);
    close(fd);
}

/* HA switches the unit while the agent still answers the view's PLAY: the
 * switch parks the client before it counts as played. It gets the new
 * unit's view instead of a view that never starts. */
static void unit_switch_during_play(void) {
    struct c300x_video_status current;
    atomic_store(&station_busy, 0);
    assert(c300x_video_activate(runtime->video, 1, NULL));
    atomic_store(&hold_play, 1);
    int fd = rtsp_open();
    assert(rtsp_play(fd, "/doorbell") == 200);
    long long deadline = __real_c300x_monotonic_ms() + WAIT_MS;
    while (atomic_load(&hold_play) != 2) {
        assert(__real_c300x_monotonic_ms() < deadline);
        usleep(5000);
    }
    assert(c300x_video_activate(runtime->video, 1, "21"));
    atomic_store(&hold_play, 0);
    wait_invites(2);
    expect_log("I20 B G I21");
    deadline = __real_c300x_monotonic_ms() + WAIT_MS;
    for (status(&current); current.clients != 1 || !current.call_active; status(&current)) {
        assert(__real_c300x_monotonic_ms() < deadline);
        usleep(5000);
    }
    c300x_video_stop(runtime->video);
    wait_byes(2);
    close(fd);
}

/* Door contact frames of bt_vct (*8*66 opened, *8*65 closed) on the
 * multicast: per unit, repeats change nothing; the first frame of a unit
 * gives it a contact (outdoor_units.changed). A frame with the qualified
 * address of the default unit is that unit. */
static void door_contacts(void) {
    char data[4096];

    assert(calls_api("GET", "/api/v1/outdoor-units", "", data, sizeof(data)) == 200);
    assert(strstr(data, "\"id\":\"20\"") && strstr(data, "\"door\":null"));
    bus("*8*66*20##");
    wait_event("door.opened", 1, data, sizeof(data));
    assert(strcmp(data, "{\"unit\":\"20\",\"where\":\"20\",\"raw\":\"*8*66*20##\"}") == 0);
    assert(count_events("outdoor_units.changed") == 1);
    bus("*8*66*20##");
    bus("*8*65*20#2##");
    wait_event("door.closed", 1, data, sizeof(data));
    assert(strstr(data, "\"unit\":\"20\",\"where\":\"20#2\""));
    assert(count_events("door.opened") == 1);
    bus("*8*66*21##");
    wait_event("door.opened", 2, data, sizeof(data));
    assert(strstr(data, "\"unit\":\"21\",\"where\":\"21\""));
    assert(calls_api("GET", "/api/v1/outdoor-units", "", data, sizeof(data)) == 200);
    assert(strstr(data, "\"id\":\"20\",\"where\":\"20#2\""));
    assert(strstr(data, "\"default\":true,\"door\":{\"state\":\"closed\",\"age_ms\":"));
    assert(strstr(data, "\"id\":\"21\",\"where\":\"21\"") && strstr(data, "\"source\":\"seen\",\"default\":false,\"door\":{\"state\":\"open\""));
    assert(count_events("door.closed") == 1 && count_events("call.caller_identified") == 0);
}

/* The station never answers the first ring REGISTER, as on a loaded host
 * where the 200 comes too late: the agent registers on its retry and the
 * ring leg works. */
static void lost_first_register(void) {
    assert(atomic_load(&ring_registers) == 2);
    unanswered();
}

int main(int argc, char **argv) {
    assert(argc == 2);
    if (strcmp(argv[1], "lost_first_register") == 0) atomic_store(&lose_ring_register, 1);
    alarm(60);
    signal(SIGPIPE, SIG_IGN);
    static struct c300x_config config;
    c300x_default_config(&config);
    config.video_enabled = 1;
    config.video_rtsp_username[0] = config.video_rtsp_password[0] = '\0';
    snprintf(config.video_sip_domain, sizeof(config.video_sip_domain), "test.local");
    snprintf(config.video_sip_local_ip, sizeof(config.video_sip_local_ip), "127.0.0.1");
    config.video_sip_use_tcp = 1;

    sip_listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in loopback = {.sin_family = AF_INET};
    loopback.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    assert(__real_bind(sip_listen_fd, (struct sockaddr *)&loopback, sizeof(loopback)) == 0);
    assert(listen(sip_listen_fd, 16) == 0);
    config.video_sip_local_port = bound_port(sip_listen_fd);
    pthread_t station;
    assert(pthread_create(&station, NULL, station_accept, NULL) == 0);

    /* A closed probe frees its port for any process on the host until the
     * agent's RTSP listener binds it. Kept bound but not listening, with
     * SO_REUSEADDR like that listener, the port stays out of every other
     * bind and connect and the listener can still take it. */
    int probe = socket(AF_INET, SOCK_STREAM, 0), reuse = 1;
    assert(setsockopt(probe, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse)) == 0);
    assert(__real_bind(probe, (struct sockaddr *)&loopback, sizeof(loopback)) == 0);
    rtsp_port = bound_port(probe);
    config.video_rtsp_port = rtsp_port;

    udp_fd = socket(AF_INET, SOCK_DGRAM, 0);
    assert(__real_bind(udp_fd, (struct sockaddr *)&loopback, sizeof(loopback)) == 0);
    udp_port = bound_port(udp_fd);

    runtime = calloc(1, sizeof(*runtime));
    assert(runtime != NULL);
    runtime->config = &config;
    c300x_call_hub_init(&runtime->calls, &config, dispatch_call_event, runtime);
    c300x_call_hub_bind(&runtime->calls, &runtime->video, &runtime->video_control);
    /* No request worker: the media operations of API requests run in place. */
    runtime->video_control.worker.armed_fd = -1;
    runtime->video_control.worker.owner_fd = C300X_REQUEST_WORKER_FREE;
    runtime->video = c300x_video_create(&config, NULL, 0);
    assert(runtime->video != NULL);
    c300x_video_set_event_callback(runtime->video, dispatch_video_event, runtime);
    c300x_video_set_ring_receiver_enabled(runtime->video, 1);
    /* The fake station knows the ring leg when the REGISTER arrives; the
     * agent is registered once it has read the 200 OK. A ring in between
     * finds no ring receiver and reports no video, as on a station whose
     * agent is still starting. */
    long long deadline = __real_c300x_monotonic_ms() + RING_REGISTERED_WAIT_MS;
    struct c300x_video_status ready;
    for (;;) {
        status(&ready);
        if (atomic_load(&ring_fd) >= 0 && ready.ring_registered) break;
        assert(__real_c300x_monotonic_ms() < deadline);
        usleep(10000);
    }
    pthread_t loop;
    assert(pthread_create(&loop, NULL, agent_loop, NULL) == 0);

    if (strcmp(argv[1], "display_answer") == 0) display_answer(false);
    else if (strcmp(argv[1], "display_answer_end_lost") == 0) display_answer(true);
    else if (strcmp(argv[1], "unanswered") == 0) unanswered();
    else if (strcmp(argv[1], "lost_first_register") == 0) lost_first_register();
    else if (strcmp(argv[1], "ha_answer") == 0) ha_answer();
    else if (strcmp(argv[1], "single_unit_as_3_0_0") == 0) single_unit_as_3_0_0();
    else if (strcmp(argv[1], "two_units") == 0) two_units();
    else if (strcmp(argv[1], "lifecycle_unanswered") == 0) lifecycle_unanswered();
    else if (strcmp(argv[1], "lifecycle_ha_answer_ha_hangup") == 0) lifecycle_ha_answer_ha_hangup();
    else if (strcmp(argv[1], "lifecycle_station_answer_station_hangup") == 0) lifecycle_station_answer_station_hangup();
    else if (strcmp(argv[1], "lifecycle_ha_answer_station_hangup") == 0) lifecycle_ha_answer_station_hangup();
    else if (strcmp(argv[1], "lifecycle_ondemand_view") == 0) lifecycle_ondemand_view();
    else if (strcmp(argv[1], "ondemand_units") == 0) ondemand_units();
    else if (strcmp(argv[1], "door_contacts") == 0) door_contacts();
    else if (strcmp(argv[1], "unit_switch_during_play") == 0) unit_switch_during_play();
    else if (strcmp(argv[1], "unviewable_unit_during_view") == 0) unviewable_unit_during_view();
    else if (strcmp(argv[1], "refused_answer_then_station") == 0) refused_answer_then_station();
    else if (strcmp(argv[1], "display_answer_without_preview") == 0) display_answer_without_preview();
    else if (strcmp(argv[1], "app_answer_end_frame_first") == 0) app_answer_end_frame_first();
    else if (strcmp(argv[1], "display_answer_end_lost_call") == 0) display_answer_end_lost_call();
    else if (strcmp(argv[1], "answer_before_caller") == 0) answer_before_caller();
    else if (strcmp(argv[1], "abandoned_answer_then_station") == 0) abandoned_answer_then_station();
    else if (strcmp(argv[1], "view_is_current") == 0) view_is_current();
    else if (strcmp(argv[1], "call_id_lengths") == 0) call_id_lengths();
    else if (strcmp(argv[1], "pending_unit_video") == 0) pending_unit_video();
    else if (strcmp(argv[1], "view_during_bus_ring") == 0) view_during_bus_ring();
    else if (strcmp(argv[1], "agent_answer_is_ha") == 0) agent_answer_is_ha();
    else if (strcmp(argv[1], "own_ring_answer_is_ha") == 0) own_ring_answer_is_ha();
    else if (strcmp(argv[1], "display_view_hangup") == 0) display_view_hangup();
    else if (strcmp(argv[1], "display_answered_hangup") == 0) display_answered_hangup();
    else if (strcmp(argv[1], "bus_ring_hangup_during_view") == 0) bus_ring_hangup_during_view();
    else if (strcmp(argv[1], "view_state6_during_bus_ring") == 0) view_state6_during_bus_ring();
    else if (strcmp(argv[1], "view_close_keeps_ring") == 0) view_close_keeps_ring();
    else if (strcmp(argv[1], "display_view_end_keeps_ring") == 0) display_view_end_keeps_ring();
    else if (strcmp(argv[1], "unanswered_bus_ring_end_frame") == 0) unanswered_bus_ring_end_frame();
    else if (strcmp(argv[1], "boot_id_at_start") == 0) boot_id_at_start();
    else if (strcmp(argv[1], "station_busy_bus_end") == 0) station_busy_case(true);
    else if (strcmp(argv[1], "station_busy_timeout") == 0) station_busy_case(false);
    else if (strcmp(argv[1], "station_freed_before_486") == 0) station_freed_during_start(true);
    else if (strcmp(argv[1], "station_freed_after_486") == 0) station_freed_during_start(false);
    else assert(!"unknown case");

    printf("ondemand_invites=%d\n", atomic_load(&ondemand_invites));
    atomic_store(&loop_stop, true);
    assert(pthread_join(loop, NULL) == 0);
    c300x_video_destroy(runtime->video);
    c300x_recent_events_clear(&runtime->recent_events);
    free(runtime);
    return 0;
}
