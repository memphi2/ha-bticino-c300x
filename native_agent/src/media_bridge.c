#define _POSIX_C_SOURCE 200809L

#include "device_user.h"
#include "media_bridge.h"
#include "sha256.h"
#include "string_util.h"
#include "video_rtsp.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#include "pthread_compat.h"

#define RTSP_BUFFER_SIZE 8192
#define SIP_BUFFER_SIZE 8192
#define SIP_DOMAIN_FILE "/etc/flexisip/domain-registration.conf"
#define DEFAULT_SIP_PORT 5060
#define BT_AV_MEDIA_PORT 30007
#define RTSP_IDLE_TIMEOUT_SECONDS 180
#define TALKBACK_TARGET_PORT 4000
#define MEDIA_AUDIO_RTP_PORT 26986
#define MEDIA_AUDIO_RTCP_PORT 26987
#define MEDIA_VIDEO_RTP_PORT 28772
#define MEDIA_VIDEO_RTCP_PORT 28773
#define MEDIA_KEEPALIVE_MS 500
#define MEDIA_AUDIO_PACKET_MS 20
#define MEDIA_AUDIO_TIMESTAMP_STEP 160
#define MEDIA_AUDIO_PAYLOAD_TYPE 98
#define MEDIA_AUDIO_SILENCE_PAYLOAD 0x00
#define MEDIA_TALKBACK_SILENCE_GRACE_MS (MEDIA_AUDIO_PACKET_MS * 2)
#define MEDIA_RENEW_SECONDS 20
#define MEDIA_SIP_KEEPALIVE_SECONDS 10
#define MEDIA_SIP_USER_AGENT "VctLinphoneService/1.17.3"
#define MEDIA_INSTANCE_UUID_LEN 37
#define MEDIA_INSTANCE_UUID_NAMESPACE "ha-bticino-c300x:sip-instance:"
#define MEDIA_SRTP_MASTER_KEY_LEN 30
#define HOME_CALL_AUDIO_RTP_PORT 45544
#define HOME_CALL_AUDIO_RTCP_PORT 45545
#define HOME_CALL_DEFAULT_RING_TIMEOUT_SECONDS 60
#define RING_AUDIO_RTP_PORT 17030
#define RING_AUDIO_RTCP_PORT 17031
#define RING_VIDEO_RTP_PORT 16718
#define RING_VIDEO_RTCP_PORT 16719
#define RING_AUDIO_PAYLOAD_TYPE 96
#define RTSP_AUDIO_PAYLOAD_TYPE 0
#define RTSP_BACKCHANNEL_STREAM_ID 2
#define RTSP_BACKCHANNEL_PCMA_PAYLOAD_TYPE 8
#define RTSP_BACKCHANNEL_PCMU_PAYLOAD_TYPE 0
#define RTSP_AUDIO_FRAME_SAMPLES 160
#define RTSP_BACKCHANNEL_FRAME_SAMPLES RTSP_AUDIO_FRAME_SAMPLES
#define RTSP_BACKCHANNEL_TALKBACK_QUEUE_FRAMES 16
#define RTSP_BACKCHANNEL_TALKBACK_PAYLOAD_MAX 256
#define RTSP_BACKCHANNEL_SPEEX_BITS_STORAGE 2048
#define RING_REGISTER_EXPIRES_SECONDS 300
#define RING_REGISTER_RENEW_SECONDS 240
#define RING_RETRY_SECONDS 5
#define RING_EARLY_MEDIA_DELAY_MS 300
#define RING_TALKBACK_SILENCE_GRACE_MS (MEDIA_AUDIO_PACKET_MS * 2)
#define RING_UNANSWERED_MEDIA_IDLE_TIMEOUT_MS 300000
#define RING_ANSWERED_MEDIA_IDLE_TIMEOUT_MS 30000
#define HOME_CALL_TALKBACK_SILENCE_GRACE_MS (MEDIA_AUDIO_PACKET_MS * 2)

static bool read_sip_domain(char *domain, size_t domain_len);
static int bind_udp_port(int port);
static int bind_udp_loopback_port(int port);
static void fill_random_bytes(unsigned char *out, size_t len);
static void secure_zero(void *ptr, size_t len);
static int16_t decode_pcmu_sample(unsigned char value);
static int16_t decode_pcma_sample(unsigned char value);
static unsigned char encode_pcmu_sample(int16_t sample);
static void store_be16(unsigned char *out, uint16_t value);
static uint16_t load_be16(const unsigned char *in);
static uint32_t load_be32(const unsigned char *in);
static void store_be32(unsigned char *out, uint32_t value);

static bool rtsp_peer_ipv4_address(
    const struct sockaddr_storage *peer,
    struct in_addr *address
) {
    if (peer->ss_family == AF_INET) {
        const struct sockaddr_in *peer4 = (const struct sockaddr_in *)peer;
        *address = peer4->sin_addr;
        return true;
    }
    if (peer->ss_family == AF_INET6) {
        const struct sockaddr_in6 *peer6 = (const struct sockaddr_in6 *)peer;
        if (IN6_IS_ADDR_V4MAPPED(&peer6->sin6_addr)) {
            memcpy(address, &peer6->sin6_addr.s6_addr[12], sizeof(*address));
            return true;
        }
    }
    return false;
}

static int video_rtp_port(const struct c300x_config *config) {
    return (int)config->video_rtp_port_start + 2;
}

static int audio_rtp_port(const struct c300x_config *config) {
    return (int)config->video_rtp_port_start;
}

static int doorbell_devaddr(const struct c300x_config *config) {
    int devaddr = atoi(config->video_sip_devaddr);
    return devaddr > 0 ? devaddr : 20;
}

typedef struct {
    bool active;
    int fd;
    bool transport_tcp;
    bool audio_enabled;
    bool recorder;
    bool backchannel_enabled;
    int video_interleaved_channel;
    int audio_interleaved_channel;
    int backchannel_interleaved_channel;
    struct sockaddr_in udp_client;
    char session_id[32];
} rtsp_client_slot_t;

typedef struct {
    int fd;
    bool transport_tcp;
    int channel;
    struct sockaddr_in udp_client;
} rtsp_send_target_t;

typedef struct {
    int fd;
    struct sockaddr_storage peer;
} rtsp_client_thread_arg_t;

typedef struct {
    unsigned char payload[RTSP_BACKCHANNEL_TALKBACK_PAYLOAD_MAX];
    size_t payload_len;
    bool marker;
} talkback_queue_frame_t;

typedef struct {
    pthread_mutex_t mutex;
    pthread_cond_t ready_cond;
    pthread_t server_thread;
    pthread_t relay_thread;
    pthread_t sip_thread;
    pthread_t ondemand_media_thread;
    pthread_t talkback_thread;
    pthread_t ring_thread;
    pthread_t home_call_thread;
    int rtsp_client_threads;
    bool running;
    bool startup_done;
    bool startup_ok;
    bool relay_started;
    bool sip_monitor_started;
    bool ondemand_media_started;
    bool talkback_started;
    bool ring_started;
    bool home_call_started;
    bool ring_registered;
    bool relay_stop;
    bool sip_stop;
    bool ondemand_media_stop;
    bool talkback_stop;
    bool ring_stop;
    bool home_call_stop;
    bool home_call_send_bye;
    bool ring_call_active;
    bool ring_media_active;
    bool ring_audio_active;
    bool ring_answered;
    bool ring_answer_requested;
    bool ring_call_stop;
    bool ring_send_bye;
    bool home_call_active;
    bool home_call_answered;
    bool home_call_rtp_proxy;
    bool media_active;
    bool media_starting;
    bool stop_in_progress;
    int listen_fd;
    int client_fd;
    int rtp_fd;
    int audio_rtp_fd;
    int ondemand_audio_rtp_fd;
    int ondemand_audio_rtcp_fd;
    int ondemand_video_rtp_fd;
    int ondemand_video_rtcp_fd;
    int talkback_fd;
    int sip_fd;
    int ring_sip_fd;
    int home_call_sip_fd;
    int ring_audio_rtp_fd;
    int ring_audio_rtcp_fd;
    int ring_video_rtp_fd;
    int ring_video_rtcp_fd;
    int home_call_audio_rtp_fd;
    int home_call_audio_rtcp_fd;
    int ondemand_target_audio_port;
    int ondemand_target_video_port;
    int ring_target_audio_port;
    int ring_target_video_port;
    int home_call_target_audio_port;
    int home_call_duration_seconds;
    unsigned long long home_call_rtp_packets;
    unsigned long long home_call_rtcp_packets;
    long long ondemand_last_talkback_ms;
    long long ring_last_talkback_ms;
    long long home_call_last_talkback_ms;
    talkback_queue_frame_t talkback_queue[RTSP_BACKCHANNEL_TALKBACK_QUEUE_FRAMES];
    size_t talkback_queue_head;
    size_t talkback_queue_len;
    int16_t talkback_pcm_buffer[RTSP_BACKCHANNEL_FRAME_SAMPLES];
    size_t talkback_pcm_count;
    bool talkback_pcm_seq_initialized;
    uint16_t talkback_pcm_next_seq;
    unsigned int talkback_backchannel_generation;
    void *ondemand_srtp_state;
    void *ring_srtp_state;
    void *home_call_srtp_state;
    unsigned char ondemand_audio_srtp_key[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char ondemand_video_srtp_key[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char ondemand_audio_srtp_in_key[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char ondemand_video_srtp_in_key[MEDIA_SRTP_MASTER_KEY_LEN];
    bool transport_tcp;
    bool rtsp_audio_enabled;
    bool rtsp_audio_out_initialized;
    uint16_t rtsp_audio_out_seq;
    uint32_t rtsp_audio_out_timestamp;
    int video_interleaved_channel;
    int audio_interleaved_channel;
    struct sockaddr_in udp_client;
    char session_id[32];
    rtsp_client_slot_t rtsp_clients[C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS];
    char domain[128];
    char from_aor[256];
    char to_aor[256];
    char sip_local_ip[64];
    char sip_transport[4];
    uint16_t sip_local_port;
    char call_id[128];
    char from_tag[64];
    char to_header[512];
    char contact_uri[512];
    char ondemand_instance_uuid[MEDIA_INSTANCE_UUID_LEN];
    char ring_instance_uuid[MEDIA_INSTANCE_UUID_LEN];
    char home_call_instance_uuid[MEDIA_INSTANCE_UUID_LEN];
    int invite_cseq;
    const struct c300x_config *config;
    struct c300x_video *video;
} media_bridge_t;

static bool start_talkback_proxy(media_bridge_t *bridge);

static media_bridge_t g_bridge = {
    .mutex = PTHREAD_MUTEX_INITIALIZER,
    .ready_cond = PTHREAD_COND_INITIALIZER,
    .listen_fd = -1,
    .client_fd = -1,
    .rtp_fd = -1,
    .audio_rtp_fd = -1,
    .ondemand_audio_rtp_fd = -1,
    .ondemand_audio_rtcp_fd = -1,
    .ondemand_video_rtp_fd = -1,
    .ondemand_video_rtcp_fd = -1,
    .sip_fd = -1,
    .talkback_fd = -1,
    .ring_sip_fd = -1,
    .home_call_sip_fd = -1,
    .ring_audio_rtp_fd = -1,
    .ring_audio_rtcp_fd = -1,
    .ring_video_rtp_fd = -1,
    .ring_video_rtcp_fd = -1,
    .home_call_audio_rtp_fd = -1,
    .home_call_audio_rtcp_fd = -1,
    .video_interleaved_channel = 2,
    .audio_interleaved_channel = 0,
};

static void close_fd_if_open(int *fd) {
    if (fd != NULL && *fd >= 0) {
        close(*fd);
        *fd = -1;
    }
}

static bool ring_preview_sharing_allowed_locked(const media_bridge_t *bridge) {
    return (
        bridge->ring_call_active
        && bridge->ring_media_active
        && !bridge->ring_audio_active
        && !bridge->ring_answered
        && !bridge->ring_call_stop
    );
}

static bool ring_answer_stream_sharing_allowed_locked(const media_bridge_t *bridge) {
    return (
        bridge->ring_call_active
        && bridge->ring_media_active
        && (bridge->ring_answer_requested || bridge->ring_answered)
        && !bridge->ring_call_stop
    );
}

static bool rtsp_client_sharing_allowed_locked(const media_bridge_t *bridge) {
    return (
        ring_preview_sharing_allowed_locked(bridge)
        || ring_answer_stream_sharing_allowed_locked(bridge)
    );
}

static int rtsp_client_count_locked(const media_bridge_t *bridge) {
    int count = 0;

    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; index++) {
        if (bridge->rtsp_clients[index].active && bridge->rtsp_clients[index].fd >= 0) {
            count++;
        }
    }
    return count;
}

static void sync_legacy_rtsp_client_locked(media_bridge_t *bridge) {
    bridge->client_fd = -1;
    bridge->transport_tcp = true;
    bridge->rtsp_audio_enabled = false;
    bridge->video_interleaved_channel = 2;
    bridge->audio_interleaved_channel = 0;
    memset(&bridge->udp_client, 0, sizeof(bridge->udp_client));
    bridge->session_id[0] = '\0';

    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; index++) {
        rtsp_client_slot_t *slot = &bridge->rtsp_clients[index];
        if (!slot->active || slot->fd < 0) {
            continue;
        }
        bridge->client_fd = slot->fd;
        bridge->transport_tcp = slot->transport_tcp;
        bridge->rtsp_audio_enabled = slot->audio_enabled;
        bridge->video_interleaved_channel = slot->video_interleaved_channel;
        bridge->audio_interleaved_channel = slot->audio_interleaved_channel;
        bridge->udp_client = slot->udp_client;
        snprintf(bridge->session_id, sizeof(bridge->session_id), "%s", slot->session_id);
        return;
    }
}

static bool register_rtsp_client_locked(media_bridge_t *bridge, int fd, int *slot_index) {
    int active_clients = rtsp_client_count_locked(bridge);

    if (active_clients > 0 && !rtsp_client_sharing_allowed_locked(bridge)) {
        return false;
    }
    if (active_clients >= C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS) {
        return false;
    }

    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; index++) {
        rtsp_client_slot_t *slot = &bridge->rtsp_clients[index];
        if (slot->active) {
            continue;
        }
        memset(slot, 0, sizeof(*slot));
        slot->active = true;
        slot->fd = fd;
        slot->transport_tcp = true;
        slot->video_interleaved_channel = 0;
        slot->audio_interleaved_channel = 0;
        slot->backchannel_interleaved_channel = -1;
        snprintf(slot->session_id, sizeof(slot->session_id), "%ld-%zu", (long)time(NULL), index);
        if (slot_index != NULL) {
            *slot_index = (int)index;
        }
        sync_legacy_rtsp_client_locked(bridge);
        return true;
    }
    return false;
}

static rtsp_client_slot_t *rtsp_client_slot_locked(media_bridge_t *bridge, int slot_index) {
    if (slot_index < 0 || slot_index >= (int)C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS) {
        return NULL;
    }
    rtsp_client_slot_t *slot = &bridge->rtsp_clients[slot_index];
    if (!slot->active || slot->fd < 0) {
        return NULL;
    }
    return slot;
}

static void unregister_rtsp_client_locked(media_bridge_t *bridge, int slot_index) {
    rtsp_client_slot_t *slot = rtsp_client_slot_locked(bridge, slot_index);

    if (slot == NULL) {
        return;
    }
    slot->active = false;
    slot->fd = -1;
    sync_legacy_rtsp_client_locked(bridge);
    pthread_cond_broadcast(&bridge->ready_cond);
}

static void shutdown_all_rtsp_clients_locked(media_bridge_t *bridge) {
    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; index++) {
        rtsp_client_slot_t *slot = &bridge->rtsp_clients[index];
        if (slot->active && slot->fd >= 0) {
            shutdown(slot->fd, SHUT_RDWR);
        }
    }
}

static void close_all_rtsp_clients_locked(media_bridge_t *bridge) {
    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; index++) {
        rtsp_client_slot_t *slot = &bridge->rtsp_clients[index];
        if (slot->active && slot->fd >= 0) {
            close(slot->fd);
        }
        memset(slot, 0, sizeof(*slot));
        slot->fd = -1;
    }
    sync_legacy_rtsp_client_locked(bridge);
}

static void shutdown_ring_preview_clients_except_locked(media_bridge_t *bridge, int keep_slot_index) {
    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS; index++) {
        rtsp_client_slot_t *slot = &bridge->rtsp_clients[index];
        if (!slot->active || slot->fd < 0 || (int)index == keep_slot_index) {
            continue;
        }
        if (!slot->audio_enabled) {
            shutdown(slot->fd, SHUT_RDWR);
        }
    }
}

static size_t rtsp_send_targets_locked(
    const media_bridge_t *bridge,
    bool audio,
    rtsp_send_target_t *targets,
    size_t targets_len
) {
    size_t count = 0;

    for (size_t index = 0; index < C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS && count < targets_len; index++) {
        const rtsp_client_slot_t *slot = &bridge->rtsp_clients[index];
        if (!slot->active || slot->fd < 0) {
            continue;
        }
        if (audio && !slot->audio_enabled) {
            continue;
        }
        targets[count].fd = slot->fd;
        targets[count].transport_tcp = slot->transport_tcp;
        targets[count].channel = audio ? slot->audio_interleaved_channel : slot->video_interleaved_channel;
        targets[count].udp_client = slot->udp_client;
        count++;
    }
    return count;
}

static bool start_bt_av_media(media_bridge_t *bridge);

typedef void *c300x_srtp_t;

typedef struct {
    int cipher_type;
    int cipher_key_len;
    int auth_type;
    int auth_key_len;
    int auth_tag_len;
    int sec_serv;
} c300x_srtp_crypto_policy_t;

typedef struct {
    int type;
    uint32_t value;
} c300x_srtp_ssrc_t;

typedef struct c300x_srtp_policy {
    c300x_srtp_ssrc_t ssrc;
    c300x_srtp_crypto_policy_t rtp;
    c300x_srtp_crypto_policy_t rtcp;
    unsigned char *key;
    void *ekt;
    unsigned long window_size;
    int allow_repeat_tx;
    struct c300x_srtp_policy *next;
} c300x_srtp_policy_t;

typedef struct {
    void *handle;
    int initialized;
    int available;
    int (*srtp_init)(void);
    int (*srtp_create)(c300x_srtp_t *session, const c300x_srtp_policy_t *policy);
    int (*srtp_dealloc)(c300x_srtp_t session);
    int (*srtp_protect)(c300x_srtp_t session, void *packet, int *len);
    int (*srtp_protect_rtcp)(c300x_srtp_t session, void *packet, int *len);
    int (*srtp_unprotect)(c300x_srtp_t session, void *packet, int *len);
    int (*srtp_unprotect_rtcp)(c300x_srtp_t session, void *packet, int *len);
    void (*crypto_policy_set_rtp_default)(c300x_srtp_crypto_policy_t *policy);
    void (*crypto_policy_set_rtcp_default)(c300x_srtp_crypto_policy_t *policy);
} c300x_srtp_api_t;

typedef struct {
    c300x_srtp_t audio;
    c300x_srtp_t video;
    c300x_srtp_t audio_in;
    c300x_srtp_t video_in;
    uint16_t audio_seq;
    uint32_t audio_timestamp;
    uint32_t audio_ssrc;
    uint32_t rtcp_sender_ssrc;
    int available;
} media_srtp_state_t;

static pthread_mutex_t g_srtp_mutex = PTHREAD_MUTEX_INITIALIZER;
static c300x_srtp_api_t g_srtp_api;

typedef struct {
    void *handle;
    int initialized;
    int available;
    const void *(*speex_lib_get_mode)(int mode);
    void *(*speex_encoder_init)(const void *mode);
    void (*speex_encoder_destroy)(void *state);
    void (*speex_bits_init)(void *bits);
    void (*speex_bits_destroy)(void *bits);
    void (*speex_bits_reset)(void *bits);
    void (*speex_bits_read_from)(void *bits, char *bytes, int len);
    int (*speex_bits_write)(void *bits, char *bytes, int max_len);
    int (*speex_encode_int)(void *state, const int16_t *in, void *bits);
    void *(*speex_decoder_init)(const void *mode);
    void (*speex_decoder_destroy)(void *state);
    int (*speex_decode_int)(void *state, void *bits, int16_t *out);
} c300x_speex_api_t;

typedef union {
    long double align;
    unsigned char bytes[RTSP_BACKCHANNEL_SPEEX_BITS_STORAGE];
} c300x_speex_bits_storage_t;

typedef struct {
    void *state;
    c300x_speex_bits_storage_t bits;
    int initialized;
} c300x_speex_state_t;

static pthread_mutex_t g_speex_mutex = PTHREAD_MUTEX_INITIALIZER;
static c300x_speex_api_t g_speex_api;
static c300x_speex_state_t g_speex_encoder;
static c300x_speex_state_t g_speex_decoder;

static int srtp_load_symbol(void *handle, const char *name, void *out, size_t out_len) {
    void *symbol = dlsym(handle, name);
    if (symbol == NULL || out == NULL || out_len != sizeof(symbol)) {
        return 0;
    }
    memcpy(out, &symbol, out_len);
    return 1;
}

static c300x_srtp_api_t *srtp_api(void) {
    pthread_mutex_lock(&g_srtp_mutex);
    if (!g_srtp_api.initialized) {
        void *handle = dlopen("libsrtp.so.1", RTLD_NOW | RTLD_LOCAL);
        g_srtp_api.initialized = 1;
        if (handle != NULL
            && srtp_load_symbol(handle, "srtp_init", &g_srtp_api.srtp_init, sizeof(g_srtp_api.srtp_init))
            && srtp_load_symbol(handle, "srtp_create", &g_srtp_api.srtp_create, sizeof(g_srtp_api.srtp_create))
            && srtp_load_symbol(handle, "srtp_dealloc", &g_srtp_api.srtp_dealloc, sizeof(g_srtp_api.srtp_dealloc))
            && srtp_load_symbol(handle, "srtp_protect", &g_srtp_api.srtp_protect, sizeof(g_srtp_api.srtp_protect))
            && srtp_load_symbol(
                handle,
                "srtp_protect_rtcp",
                &g_srtp_api.srtp_protect_rtcp,
                sizeof(g_srtp_api.srtp_protect_rtcp)
            )
            && srtp_load_symbol(
                handle,
                "srtp_unprotect",
                &g_srtp_api.srtp_unprotect,
                sizeof(g_srtp_api.srtp_unprotect)
            )
            && srtp_load_symbol(
                handle,
                "srtp_unprotect_rtcp",
                &g_srtp_api.srtp_unprotect_rtcp,
                sizeof(g_srtp_api.srtp_unprotect_rtcp)
            )
            && srtp_load_symbol(
                handle,
                "crypto_policy_set_rtp_default",
                &g_srtp_api.crypto_policy_set_rtp_default,
                sizeof(g_srtp_api.crypto_policy_set_rtp_default)
            )
            && srtp_load_symbol(
                handle,
                "crypto_policy_set_rtcp_default",
                &g_srtp_api.crypto_policy_set_rtcp_default,
                sizeof(g_srtp_api.crypto_policy_set_rtcp_default)
            )
            && g_srtp_api.srtp_init() == 0) {
            g_srtp_api.handle = handle;
            g_srtp_api.available = 1;
        } else {
            if (handle != NULL) {
                dlclose(handle);
            }
            memset(&g_srtp_api, 0, sizeof(g_srtp_api));
            g_srtp_api.initialized = 1;
        }
    }
    c300x_srtp_api_t *api = g_srtp_api.available ? &g_srtp_api : NULL;
    pthread_mutex_unlock(&g_srtp_mutex);
    return api;
}

static c300x_speex_api_t *speex_api(void) {
    pthread_mutex_lock(&g_speex_mutex);
    if (!g_speex_api.initialized) {
        void *handle = dlopen("libspeex.so.1", RTLD_NOW | RTLD_LOCAL);
        g_speex_api.initialized = 1;
        if (handle != NULL
            && srtp_load_symbol(
                handle,
                "speex_lib_get_mode",
                &g_speex_api.speex_lib_get_mode,
                sizeof(g_speex_api.speex_lib_get_mode)
            )
            && srtp_load_symbol(
                handle,
                "speex_encoder_init",
                &g_speex_api.speex_encoder_init,
                sizeof(g_speex_api.speex_encoder_init)
            )
            && srtp_load_symbol(
                handle,
                "speex_encoder_destroy",
                &g_speex_api.speex_encoder_destroy,
                sizeof(g_speex_api.speex_encoder_destroy)
            )
            && srtp_load_symbol(
                handle,
                "speex_bits_init",
                &g_speex_api.speex_bits_init,
                sizeof(g_speex_api.speex_bits_init)
            )
            && srtp_load_symbol(
                handle,
                "speex_bits_destroy",
                &g_speex_api.speex_bits_destroy,
                sizeof(g_speex_api.speex_bits_destroy)
            )
            && srtp_load_symbol(
                handle,
                "speex_bits_reset",
                &g_speex_api.speex_bits_reset,
                sizeof(g_speex_api.speex_bits_reset)
            )
            && srtp_load_symbol(
                handle,
                "speex_bits_write",
                &g_speex_api.speex_bits_write,
                sizeof(g_speex_api.speex_bits_write)
            )
            && srtp_load_symbol(
                handle,
                "speex_bits_read_from",
                &g_speex_api.speex_bits_read_from,
                sizeof(g_speex_api.speex_bits_read_from)
            )
            && srtp_load_symbol(
                handle,
                "speex_encode_int",
                &g_speex_api.speex_encode_int,
                sizeof(g_speex_api.speex_encode_int)
            )
            && srtp_load_symbol(
                handle,
                "speex_decoder_init",
                &g_speex_api.speex_decoder_init,
                sizeof(g_speex_api.speex_decoder_init)
            )
            && srtp_load_symbol(
                handle,
                "speex_decoder_destroy",
                &g_speex_api.speex_decoder_destroy,
                sizeof(g_speex_api.speex_decoder_destroy)
            )
            && srtp_load_symbol(
                handle,
                "speex_decode_int",
                &g_speex_api.speex_decode_int,
                sizeof(g_speex_api.speex_decode_int)
            )) {
            g_speex_api.handle = handle;
            g_speex_api.available = 1;
        } else {
            if (handle != NULL) {
                dlclose(handle);
            }
            memset(&g_speex_api, 0, sizeof(g_speex_api));
            g_speex_api.initialized = 1;
        }
    }
    c300x_speex_api_t *api = g_speex_api.available ? &g_speex_api : NULL;
    pthread_mutex_unlock(&g_speex_mutex);
    return api;
}

static bool speex_encode_pcm_frame(
    const int16_t *samples,
    unsigned char *out,
    size_t out_len,
    size_t *encoded_len
) {
    bool ok = false;
    c300x_speex_api_t *api = speex_api();

    if (api == NULL || samples == NULL || out == NULL || encoded_len == NULL) {
        return false;
    }
    pthread_mutex_lock(&g_speex_mutex);
    if (!g_speex_encoder.initialized) {
        const void *mode = api->speex_lib_get_mode(0);
        g_speex_encoder.state = mode != NULL ? api->speex_encoder_init(mode) : NULL;
        if (g_speex_encoder.state != NULL) {
            api->speex_bits_init(g_speex_encoder.bits.bytes);
            g_speex_encoder.initialized = 1;
        }
    }
    if (g_speex_encoder.initialized && g_speex_encoder.state != NULL) {
        int written;
        api->speex_bits_reset(g_speex_encoder.bits.bytes);
        (void)api->speex_encode_int(
            g_speex_encoder.state,
            samples,
            g_speex_encoder.bits.bytes
        );
        written = api->speex_bits_write(
            g_speex_encoder.bits.bytes,
            (char *)out,
            (int)out_len
        );
        if (written > 0 && (size_t)written <= out_len) {
            *encoded_len = (size_t)written;
            ok = true;
        }
    }
    pthread_mutex_unlock(&g_speex_mutex);
    return ok;
}

static bool speex_decode_audio_frame(
    const unsigned char *payload,
    size_t payload_len,
    int16_t *samples,
    size_t sample_count
) {
    bool ok = false;
    c300x_speex_api_t *api = speex_api();

    if (
        api == NULL
        || payload == NULL
        || payload_len == 0
        || samples == NULL
        || sample_count < RTSP_AUDIO_FRAME_SAMPLES
    ) {
        return false;
    }
    pthread_mutex_lock(&g_speex_mutex);
    if (!g_speex_decoder.initialized) {
        const void *mode = api->speex_lib_get_mode(0);
        g_speex_decoder.state = mode != NULL ? api->speex_decoder_init(mode) : NULL;
        if (g_speex_decoder.state != NULL) {
            api->speex_bits_init(g_speex_decoder.bits.bytes);
            g_speex_decoder.initialized = 1;
        }
    }
    if (g_speex_decoder.initialized && g_speex_decoder.state != NULL) {
        api->speex_bits_reset(g_speex_decoder.bits.bytes);
        api->speex_bits_read_from(
            g_speex_decoder.bits.bytes,
            (char *)payload,
            (int)payload_len
        );
        ok = api->speex_decode_int(
            g_speex_decoder.state,
            g_speex_decoder.bits.bytes,
            samples
        ) == 0;
    }
    pthread_mutex_unlock(&g_speex_mutex);
    return ok;
}

static int create_srtp_session(c300x_srtp_api_t *api, const unsigned char *key, c300x_srtp_t *session) {
    c300x_srtp_policy_t policy;

    if (api == NULL || key == NULL || session == NULL) {
        return 0;
    }
    memset(&policy, 0, sizeof(policy));
    policy.ssrc.type = 3; /* ssrc_any_outbound in libsrtp 1.x. */
    api->crypto_policy_set_rtp_default(&policy.rtp);
    api->crypto_policy_set_rtcp_default(&policy.rtcp);
    policy.key = (unsigned char *)key;
    policy.window_size = 128;
    policy.allow_repeat_tx = 1;
    return api->srtp_create(session, &policy) == 0;
}

static int create_srtp_inbound_session(c300x_srtp_api_t *api, const unsigned char *key, c300x_srtp_t *session) {
    c300x_srtp_policy_t policy;

    if (api == NULL || key == NULL || session == NULL) {
        return 0;
    }
    memset(&policy, 0, sizeof(policy));
    policy.ssrc.type = 2; /* ssrc_any_inbound in libsrtp 1.x. */
    api->crypto_policy_set_rtp_default(&policy.rtp);
    api->crypto_policy_set_rtcp_default(&policy.rtcp);
    policy.key = (unsigned char *)key;
    policy.window_size = 128;
    policy.allow_repeat_tx = 1;
    return api->srtp_create(session, &policy) == 0;
}

static int media_srtp_init_state(
    media_srtp_state_t *state,
    const unsigned char *audio_key,
    const unsigned char *video_key
) {
    c300x_srtp_api_t *api = srtp_api();

    if (api == NULL || state == NULL) {
        return 0;
    }
    memset(state, 0, sizeof(*state));
    if (!create_srtp_session(api, audio_key, &state->audio)) {
        return 0;
    }
    if (!create_srtp_session(api, video_key, &state->video)) {
        api->srtp_dealloc(state->audio);
        memset(state, 0, sizeof(*state));
        return 0;
    }
    fill_random_bytes((unsigned char *)&state->audio_ssrc, sizeof(state->audio_ssrc));
    fill_random_bytes((unsigned char *)&state->rtcp_sender_ssrc, sizeof(state->rtcp_sender_ssrc));
    fill_random_bytes((unsigned char *)&state->audio_seq, sizeof(state->audio_seq));
    fill_random_bytes((unsigned char *)&state->audio_timestamp, sizeof(state->audio_timestamp));
    if (state->audio_ssrc == 0) {
        state->audio_ssrc = 0x48414341U;
    }
    if (state->rtcp_sender_ssrc == 0) {
        state->rtcp_sender_ssrc = 0x48414352U;
    }
    state->available = 1;
    return 1;
}

static int media_srtp_init_audio_state(media_srtp_state_t *state, const unsigned char *audio_key) {
    c300x_srtp_api_t *api = srtp_api();

    if (api == NULL || state == NULL) {
        return 0;
    }
    memset(state, 0, sizeof(*state));
    if (!create_srtp_session(api, audio_key, &state->audio)) {
        return 0;
    }
    fill_random_bytes((unsigned char *)&state->audio_ssrc, sizeof(state->audio_ssrc));
    fill_random_bytes((unsigned char *)&state->rtcp_sender_ssrc, sizeof(state->rtcp_sender_ssrc));
    fill_random_bytes((unsigned char *)&state->audio_seq, sizeof(state->audio_seq));
    fill_random_bytes((unsigned char *)&state->audio_timestamp, sizeof(state->audio_timestamp));
    if (state->audio_ssrc == 0) {
        state->audio_ssrc = 0x48414341U;
    }
    if (state->rtcp_sender_ssrc == 0) {
        state->rtcp_sender_ssrc = 0x48414352U;
    }
    state->available = 1;
    return 1;
}

static void media_srtp_deinit_state(media_srtp_state_t *state) {
    c300x_srtp_api_t *api = srtp_api();

    if (api == NULL || state == NULL) {
        return;
    }
    if (state->audio != NULL) {
        api->srtp_dealloc(state->audio);
    }
    if (state->video != NULL) {
        api->srtp_dealloc(state->video);
    }
    if (state->audio_in != NULL) {
        api->srtp_dealloc(state->audio_in);
    }
    if (state->video_in != NULL) {
        api->srtp_dealloc(state->video_in);
    }
    memset(state, 0, sizeof(*state));
}

static int media_srtp_init_inbound(
    media_srtp_state_t *state,
    const unsigned char *audio_key,
    const unsigned char *video_key
) {
    c300x_srtp_api_t *api = srtp_api();

    if (api == NULL || state == NULL) {
        return 0;
    }
    if (!create_srtp_inbound_session(api, audio_key, &state->audio_in)) {
        return 0;
    }
    if (!create_srtp_inbound_session(api, video_key, &state->video_in)) {
        api->srtp_dealloc(state->audio_in);
        state->audio_in = NULL;
        return 0;
    }
    return 1;
}

static int media_srtp_init_audio_inbound(media_srtp_state_t *state, const unsigned char *audio_key) {
    c300x_srtp_api_t *api = srtp_api();

    if (api == NULL || state == NULL) {
        return 0;
    }
    return create_srtp_inbound_session(api, audio_key, &state->audio_in);
}

static void send_stun_binding_request(int fd, int port);
static void send_media_audio_silence(int fd, int port, media_srtp_state_t *state);
static void send_media_audio_silence_payload_type(
    int fd,
    int port,
    media_srtp_state_t *state,
    unsigned char payload_type
);
static bool send_queued_talkback_payload_locked(
    media_bridge_t *bridge,
    int fd,
    int port,
    media_srtp_state_t *state,
    unsigned char payload_type,
    long long *last_talkback_ms
);
static void send_srtcp_receiver_report(int fd, int port, c300x_srtp_t session, uint32_t sender_ssrc);
static void send_srtcp_pli(
    int fd,
    int port,
    c300x_srtp_t session,
    uint32_t sender_ssrc,
    uint32_t media_ssrc
);

static ssize_t send_all(int fd, const void *buf, size_t len) {
    const char *p = buf;
    size_t left = len;
    while (left > 0) {
        ssize_t n = send(fd, p, left, MSG_NOSIGNAL);
        if (n <= 0) {
            return n;
        }
        p += n;
        left -= (size_t)n;
    }
    return (ssize_t)len;
}

static int connect_local_tcp(int port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        return -1;
    }

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr) != 1) {
        close(fd);
        return -1;
    }

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static bool copy_checked(char *out, size_t out_len, const char *value) {
    if (out == NULL || out_len == 0 || value == NULL) {
        return false;
    }
    if (snprintf(out, out_len, "%s", value) >= (int)out_len) {
        out[0] = '\0';
        return false;
    }
    return true;
}

static bool sip_string_is_safe(const char *value) {
    if (value == NULL || value[0] == '\0') {
        return false;
    }
    for (const char *ptr = value; *ptr != '\0'; ptr++) {
        if (*ptr == ' ' || *ptr == '\t' || *ptr == '\r' || *ptr == '\n' || *ptr == '<' || *ptr == '>') {
            return false;
        }
    }
    return true;
}

static bool sip_domain_from_config(
    const struct c300x_config *config,
    char *domain,
    size_t domain_len
) {
    if (config != NULL && config->video_sip_domain[0] != '\0') {
        return copy_checked(domain, domain_len, config->video_sip_domain) && sip_string_is_safe(domain);
    }
    return read_sip_domain(domain, domain_len);
}

static bool sip_local_endpoint_from_config(
    const struct c300x_config *config,
    char *local_ip,
    size_t local_ip_len,
    uint16_t *local_port,
    const char **transport
) {
    const char *configured_ip = "127.0.0.1";
    uint16_t configured_port = DEFAULT_SIP_PORT;

    if (config != NULL && config->video_sip_local_ip[0] != '\0') {
        configured_ip = config->video_sip_local_ip;
    }
    if (strcmp(configured_ip, "localhost") == 0) {
        configured_ip = "127.0.0.1";
    }
    if (!copy_checked(local_ip, local_ip_len, configured_ip)) {
        return false;
    }
    if (config != NULL && config->video_sip_local_port != 0) {
        configured_port = config->video_sip_local_port;
    }
    if (local_port != NULL) {
        *local_port = configured_port;
    }
    if (transport != NULL) {
        *transport = (config == NULL || config->video_sip_use_tcp) ? "TCP" : "UDP";
    }
    return true;
}

static int connect_sip_socket(const struct c300x_config *config) {
    char local_ip[64];
    uint16_t local_port;
    const char *transport;
    int type;
    int fd;
    struct sockaddr_in addr;

    if (!sip_local_endpoint_from_config(config, local_ip, sizeof(local_ip), &local_port, &transport)) {
        return -1;
    }
    type = strcmp(transport, "TCP") == 0 ? SOCK_STREAM : SOCK_DGRAM;
    fd = socket(AF_INET, type, 0);
    if (fd < 0) {
        return -1;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(local_port);
    if (inet_pton(AF_INET, local_ip, &addr.sin_addr) != 1) {
        close(fd);
        return -1;
    }
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static void header_value(const char *message, const char *name, char *out, size_t out_len) {
    out[0] = '\0';
    size_t name_len = strlen(name);
    const char *line = message;
    while (line != NULL && *line != '\0') {
        const char *line_end = strstr(line, "\r\n");
        if (line_end == NULL) {
            line_end = line + strlen(line);
        }
        if (strncasecmp(line, name, name_len) == 0) {
            const char *value = line + name_len;
            while (*value == ' ' || *value == '\t') {
                value++;
            }
            size_t len = (size_t)(line_end - value);
            if (len >= out_len) {
                len = out_len - 1;
            }
            memcpy(out, value, len);
            out[len] = '\0';
            return;
        }
        if (*line_end == '\0') {
            break;
        }
        line = line_end + 2;
    }
}

static void sip_uri_from_header(const char *header, char *out, size_t out_len) {
    out[0] = '\0';
    if (header == NULL || header[0] == '\0' || out_len == 0) {
        return;
    }

    const char *start = strchr(header, '<');
    const char *end = NULL;
    if (start != NULL) {
        start++;
        end = strchr(start, '>');
    } else {
        start = header;
        while (*start == ' ' || *start == '\t') {
            start++;
        }
        end = start;
        while (*end != '\0' && *end != ',' && *end != '\r' && *end != '\n') {
            end++;
        }
    }

    if (start == NULL || end == NULL || end <= start) {
        return;
    }
    size_t len = (size_t)(end - start);
    if (len >= out_len) {
        len = out_len - 1;
    }
    memcpy(out, start, len);
    out[len] = '\0';
}

static void append_all_headers(
    char *out,
    size_t out_len,
    size_t *used,
    const char *message,
    const char *name
) {
    size_t name_len = strlen(name);
    const char *line = message;

    while (line != NULL && *line != '\0') {
        const char *line_end = strstr(line, "\r\n");
        if (line_end == NULL) {
            line_end = line + strlen(line);
        }
        if (strncasecmp(line, name, name_len) == 0) {
            size_t len = (size_t)(line_end - line);
            if (*used + len + 2 < out_len) {
                memcpy(out + *used, line, len);
                *used += len;
                memcpy(out + *used, "\r\n", 2);
                *used += 2;
                out[*used] = '\0';
            }
        }
        if (*line_end == '\0') {
            break;
        }
        line = line_end + 2;
    }
}

static void make_tagged_to(const char *to_header, const char *tag, char *out, size_t out_len) {
    char uri[512];

    sip_uri_from_header(to_header, uri, sizeof(uri));
    if (uri[0] != '\0') {
        snprintf(out, out_len, "<%s>;tag=%s", uri, tag);
        return;
    }
    snprintf(out, out_len, "%s;tag=%s", to_header, tag);
}

static int content_length(const char *message) {
    char value[32];
    header_value(message, "Content-Length:", value, sizeof(value));
    return value[0] ? atoi(value) : 0;
}

static long long monotonic_ms(void) {
    struct timeval now;
    gettimeofday(&now, NULL);
    return ((long long)now.tv_sec * 1000LL) + ((long long)now.tv_usec / 1000LL);
}

static bool ring_talkback_recent_locked(const media_bridge_t *bridge, long long now) {
    return bridge->ring_last_talkback_ms > 0
        && now - bridge->ring_last_talkback_ms <= RING_TALKBACK_SILENCE_GRACE_MS;
}

static bool ondemand_talkback_recent_locked(const media_bridge_t *bridge, long long now) {
    return bridge->ondemand_last_talkback_ms > 0
        && now - bridge->ondemand_last_talkback_ms <= MEDIA_TALKBACK_SILENCE_GRACE_MS;
}

static bool home_call_talkback_recent_locked(const media_bridge_t *bridge, long long now) {
    return bridge->home_call_last_talkback_ms > 0
        && now - bridge->home_call_last_talkback_ms <= HOME_CALL_TALKBACK_SILENCE_GRACE_MS;
}

static void reset_backchannel_talkback_locked(media_bridge_t *bridge) {
    if (bridge == NULL) {
        return;
    }
    bridge->talkback_queue_head = 0;
    bridge->talkback_queue_len = 0;
    bridge->talkback_pcm_count = 0;
    bridge->talkback_pcm_seq_initialized = false;
    bridge->talkback_pcm_next_seq = 0;
    bridge->talkback_backchannel_generation++;
    bridge->rtsp_audio_out_initialized = false;
    bridge->rtsp_audio_out_seq = 0;
    bridge->rtsp_audio_out_timestamp = 0;
}

static bool queue_talkback_payload_locked(
    media_bridge_t *bridge,
    const unsigned char *payload,
    size_t payload_len,
    bool marker,
    unsigned int generation
) {
    size_t index;

    if (
        bridge == NULL
        || payload == NULL
        || payload_len == 0
        || payload_len > RTSP_BACKCHANNEL_TALKBACK_PAYLOAD_MAX
        || bridge->talkback_backchannel_generation != generation
    ) {
        return false;
    }
    if (bridge->talkback_queue_len == RTSP_BACKCHANNEL_TALKBACK_QUEUE_FRAMES) {
        bridge->talkback_queue_head = (
            bridge->talkback_queue_head + 1
        ) % RTSP_BACKCHANNEL_TALKBACK_QUEUE_FRAMES;
        bridge->talkback_queue_len--;
    }
    index = (
        bridge->talkback_queue_head + bridge->talkback_queue_len
    ) % RTSP_BACKCHANNEL_TALKBACK_QUEUE_FRAMES;
    memcpy(bridge->talkback_queue[index].payload, payload, payload_len);
    bridge->talkback_queue[index].payload_len = payload_len;
    bridge->talkback_queue[index].marker = marker;
    bridge->talkback_queue_len++;
    return true;
}

static bool pop_talkback_payload_locked(
    media_bridge_t *bridge,
    unsigned char *payload,
    size_t *payload_len,
    bool *marker
) {
    const talkback_queue_frame_t *frame;

    if (
        bridge == NULL
        || payload == NULL
        || payload_len == NULL
        || marker == NULL
        || bridge->talkback_queue_len == 0
    ) {
        return false;
    }
    frame = &bridge->talkback_queue[bridge->talkback_queue_head];
    memcpy(payload, frame->payload, frame->payload_len);
    *payload_len = frame->payload_len;
    *marker = frame->marker;
    bridge->talkback_queue_head = (
        bridge->talkback_queue_head + 1
    ) % RTSP_BACKCHANNEL_TALKBACK_QUEUE_FRAMES;
    bridge->talkback_queue_len--;
    return true;
}

static int read_message(int fd, char *buffer, size_t buffer_size, int timeout_seconds) {
    size_t used = 0;
    buffer[0] = '\0';
    while (used < buffer_size - 1) {
        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(fd, &readfds);
        struct timeval timeout = {timeout_seconds, 0};
        int ready = select(fd + 1, &readfds, NULL, NULL, &timeout);
        if (ready <= 0) {
            return used > 0 ? (int)used : -1;
        }
        ssize_t n = recv(fd, buffer + used, buffer_size - used - 1, 0);
        if (n <= 0) {
            return used > 0 ? (int)used : -1;
        }
        used += (size_t)n;
        buffer[used] = '\0';
        char *header_end = strstr(buffer, "\r\n\r\n");
        if (header_end != NULL) {
            size_t header_len = (size_t)(header_end + 4 - buffer);
            int body_len = content_length(buffer);
            if ((int)(used - header_len) >= body_len) {
                return (int)used;
            }
        }
    }
    return (int)used;
}

static int read_message_poll(int fd, char *buffer, size_t buffer_size, int timeout_seconds) {
    fd_set readfds;
    FD_ZERO(&readfds);
    FD_SET(fd, &readfds);
    struct timeval timeout = {timeout_seconds, 0};
    int ready = select(fd + 1, &readfds, NULL, NULL, &timeout);
    if (ready == 0) {
        return 0;
    }
    if (ready < 0) {
        return -1;
    }
    return read_message(fd, buffer, buffer_size, timeout_seconds);
}

typedef enum {
    RTSP_READ_ERROR = -1,
    RTSP_READ_TIMEOUT = 0,
    RTSP_READ_REQUEST = 1,
    RTSP_READ_INTERLEAVED = 2,
} rtsp_read_result_t;

static int recv_exact_timeout(
    int fd,
    unsigned char *buffer,
    size_t len,
    int timeout_seconds
) {
    size_t used = 0;

    while (used < len) {
        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(fd, &readfds);
        struct timeval timeout = {timeout_seconds, 0};
        int ready = select(fd + 1, &readfds, NULL, NULL, &timeout);
        if (ready <= 0) {
            return used > 0 ? -1 : 0;
        }
        ssize_t n = recv(fd, buffer + used, len - used, 0);
        if (n <= 0) {
            return -1;
        }
        used += (size_t)n;
    }
    return 1;
}

static void drain_rtsp_interleaved_payload(
    int fd,
    size_t len,
    int timeout_seconds
) {
    unsigned char scratch[256];
    size_t remaining = len;

    while (remaining > 0) {
        size_t chunk = remaining < sizeof(scratch) ? remaining : sizeof(scratch);
        int ok = recv_exact_timeout(fd, scratch, chunk, timeout_seconds);
        if (ok <= 0) {
            return;
        }
        remaining -= chunk;
    }
}

static rtsp_read_result_t read_rtsp_request_or_interleaved(
    int fd,
    char *request,
    size_t request_size,
    unsigned char *interleaved,
    size_t interleaved_size,
    int *interleaved_channel,
    size_t *interleaved_len,
    int timeout_seconds
) {
    unsigned char first;
    size_t used;
    int ok;

    if (
        request == NULL
        || request_size < 2
        || interleaved == NULL
        || interleaved_channel == NULL
        || interleaved_len == NULL
    ) {
        return RTSP_READ_ERROR;
    }
    request[0] = '\0';
    *interleaved_channel = -1;
    *interleaved_len = 0;

    ok = recv_exact_timeout(fd, &first, 1, timeout_seconds);
    if (ok == 0) {
        return RTSP_READ_TIMEOUT;
    }
    if (ok < 0) {
        return RTSP_READ_ERROR;
    }
    if (first == '$') {
        unsigned char header[3];
        size_t frame_len;
        ok = recv_exact_timeout(fd, header, sizeof(header), timeout_seconds);
        if (ok <= 0) {
            return RTSP_READ_ERROR;
        }
        frame_len = ((size_t)header[1] << 8) | header[2];
        *interleaved_channel = header[0];
        if (frame_len > interleaved_size) {
            drain_rtsp_interleaved_payload(fd, frame_len, timeout_seconds);
            return RTSP_READ_INTERLEAVED;
        }
        ok = recv_exact_timeout(fd, interleaved, frame_len, timeout_seconds);
        if (ok <= 0) {
            return RTSP_READ_ERROR;
        }
        *interleaved_len = frame_len;
        return RTSP_READ_INTERLEAVED;
    }

    used = 1;
    request[0] = (char)first;
    request[1] = '\0';
    while (used < request_size - 1) {
        char *header_end = strstr(request, "\r\n\r\n");
        if (header_end != NULL) {
            size_t header_len = (size_t)(header_end + 4 - request);
            int body_len = content_length(request);
            if ((int)(used - header_len) >= body_len) {
                return RTSP_READ_REQUEST;
            }
        }
        ok = recv_exact_timeout(
            fd,
            (unsigned char *)request + used,
            1,
            timeout_seconds
        );
        if (ok <= 0) {
            return RTSP_READ_ERROR;
        }
        used++;
        request[used] = '\0';
    }
    return RTSP_READ_REQUEST;
}

static bool read_sip_domain(char *domain, size_t domain_len) {
    FILE *fp = fopen(SIP_DOMAIN_FILE, "r");
    if (fp == NULL) {
        return false;
    }
    if (fgets(domain, (int)domain_len, fp) == NULL) {
        fclose(fp);
        return false;
    }
    fclose(fp);
    for (char *p = domain; *p != '\0'; p++) {
        if (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') {
            *p = '\0';
            break;
        }
    }
    return domain[0] != '\0';
}

static bool media_identity_from_flexisip(
    const char *domain_hint,
    char *domain,
    size_t domain_len,
    char *from_user,
    size_t from_user_len,
    char *from_aor,
    size_t from_aor_len,
    char *to_aor,
    size_t to_aor_len
) {
    struct c300x_device_user_identity identity;

    if (!c300x_device_user_media_identity(domain_hint, &identity)) {
        return false;
    }
    return copy_checked(domain, domain_len, identity.domain)
        && copy_checked(from_user, from_user_len, identity.from_user)
        && copy_checked(from_aor, from_aor_len, identity.from_aor)
        && copy_checked(to_aor, to_aor_len, identity.to_aor);
}

static void fill_random_bytes(unsigned char *out, size_t len) {
    FILE *fp = fopen("/dev/urandom", "rb");
    size_t done = 0;

    if (fp != NULL) {
        done = fread(out, 1, len, fp);
        fclose(fp);
    }
    if (done < len) {
        unsigned int seed = (unsigned int)time(NULL) ^ (unsigned int)getpid() ^ (unsigned int)(uintptr_t)out;
        for (size_t index = done; index < len; index++) {
            seed = seed * 1103515245U + 12345U;
            out[index] = (unsigned char)((seed >> 16) & 0xff);
        }
    }
}

static bool format_uuid_bytes(const unsigned char *bytes, char *out, size_t out_len) {
    if (bytes == NULL || out == NULL || out_len < MEDIA_INSTANCE_UUID_LEN) {
        return false;
    }
    return snprintf(
        out,
        out_len,
        "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        bytes[0],
        bytes[1],
        bytes[2],
        bytes[3],
        bytes[4],
        bytes[5],
        bytes[6],
        bytes[7],
        bytes[8],
        bytes[9],
        bytes[10],
        bytes[11],
        bytes[12],
        bytes[13],
        bytes[14],
        bytes[15]
    ) == MEDIA_INSTANCE_UUID_LEN - 1;
}

static bool random_uuid_string(char *out, size_t out_len) {
    unsigned char bytes[16];

    if (out == NULL || out_len < MEDIA_INSTANCE_UUID_LEN) {
        return false;
    }
    fill_random_bytes(bytes, sizeof(bytes));
    bytes[6] = (unsigned char)((bytes[6] & 0x0f) | 0x40);
    bytes[8] = (unsigned char)((bytes[8] & 0x3f) | 0x80);
    return format_uuid_bytes(bytes, out, out_len);
}

static const char *media_instance_seed(const struct c300x_config *config) {
    if (config == NULL) {
        return NULL;
    }
    if (config->api_token[0] != '\0') {
        return config->api_token;
    }
    if (config->api_file_token[0] != '\0') {
        return config->api_file_token;
    }
    if (config->maintenance_admin_token[0] != '\0') {
        return config->maintenance_admin_token;
    }
    return NULL;
}

static bool derived_uuid_string(
    const struct c300x_config *config,
    const char *mode,
    char *out,
    size_t out_len
) {
    unsigned char digest[C300X_SHA256_DIGEST_LEN];
    const char *seed = media_instance_seed(config);
    bool ok;

    if (seed == NULL || mode == NULL || out == NULL || out_len < MEDIA_INSTANCE_UUID_LEN) {
        return false;
    }
    ok = c300x_sha256_strings3(MEDIA_INSTANCE_UUID_NAMESPACE, mode, seed, digest);
    if (!ok) {
        return false;
    }
    digest[6] = (unsigned char)((digest[6] & 0x0f) | 0x40);
    digest[8] = (unsigned char)((digest[8] & 0x3f) | 0x80);
    ok = format_uuid_bytes(digest, out, out_len);
    secure_zero(digest, sizeof(digest));
    return ok;
}

static bool bridge_instance_uuid(
    media_bridge_t *bridge,
    char *stored,
    const char *mode,
    char *out,
    size_t out_len
) {
    bool ok = true;

    if (bridge == NULL || stored == NULL || out == NULL || out_len == 0) {
        return false;
    }
    pthread_mutex_lock(&bridge->mutex);
    if (stored[0] == '\0') {
        ok = derived_uuid_string(bridge->config, mode, stored, MEDIA_INSTANCE_UUID_LEN)
            || random_uuid_string(stored, MEDIA_INSTANCE_UUID_LEN);
    }
    if (ok) {
        snprintf(out, out_len, "%s", stored);
    }
    pthread_mutex_unlock(&bridge->mutex);
    return ok;
}

static bool base64_encode(const unsigned char *data, size_t len, char *out, size_t out_len) {
    static const char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    size_t needed = ((len + 2) / 3) * 4;
    size_t pos = 0;

    if (out_len <= needed) {
        return false;
    }
    for (size_t index = 0; index < len; index += 3) {
        unsigned int value = ((unsigned int)data[index]) << 16;
        int remaining = (int)(len - index);
        if (remaining > 1) {
            value |= ((unsigned int)data[index + 1]) << 8;
        }
        if (remaining > 2) {
            value |= (unsigned int)data[index + 2];
        }
        out[pos++] = alphabet[(value >> 18) & 0x3f];
        out[pos++] = alphabet[(value >> 12) & 0x3f];
        out[pos++] = remaining > 1 ? alphabet[(value >> 6) & 0x3f] : '=';
        out[pos++] = remaining > 2 ? alphabet[value & 0x3f] : '=';
    }
    out[pos] = '\0';
    return true;
}

static int base64_value(char ch) {
    if (ch >= 'A' && ch <= 'Z') {
        return ch - 'A';
    }
    if (ch >= 'a' && ch <= 'z') {
        return ch - 'a' + 26;
    }
    if (ch >= '0' && ch <= '9') {
        return ch - '0' + 52;
    }
    if (ch == '+') {
        return 62;
    }
    if (ch == '/') {
        return 63;
    }
    return -1;
}

static bool base64_decode(const char *text, unsigned char *out, size_t out_len, size_t *decoded_len) {
    size_t pos = 0;
    int values[4];
    int count = 0;

    if (text == NULL || out == NULL || decoded_len == NULL) {
        return false;
    }
    *decoded_len = 0;
    while (*text != '\0' && *text != '\r' && *text != '\n' && *text != ';' && *text != '|') {
        if (*text == '=') {
            values[count++] = -2;
        } else {
            int value = base64_value(*text);
            if (value < 0) {
                return false;
            }
            values[count++] = value;
        }
        text++;
        if (count != 4) {
            continue;
        }
        if (values[0] < 0 || values[1] < 0) {
            return false;
        }
        if (pos >= out_len) {
            return false;
        }
        out[pos++] = (unsigned char)((values[0] << 2) | (values[1] >> 4));
        if (values[2] != -2) {
            if (values[2] < 0 || pos >= out_len) {
                return false;
            }
            out[pos++] = (unsigned char)(((values[1] & 0x0f) << 4) | (values[2] >> 2));
        }
        if (values[2] == -2 && values[3] != -2) {
            return false;
        }
        if (values[3] != -2) {
            if (values[3] < 0 || pos >= out_len) {
                return false;
            }
            out[pos++] = (unsigned char)(((values[2] & 0x03) << 6) | values[3]);
        }
        count = 0;
    }
    if (count != 0) {
        return false;
    }
    *decoded_len = pos;
    return true;
}

static bool generate_sdes_key(unsigned char *key, size_t key_len, char *out, size_t out_len) {
    if (key == NULL || key_len != MEDIA_SRTP_MASTER_KEY_LEN) {
        return false;
    }
    fill_random_bytes(key, key_len);
    return base64_encode(key, key_len, out, out_len);
}

static bool generate_random_sdes_key(size_t key_len, char *out, size_t out_len) {
    unsigned char key[64];
    bool ok;

    if (key_len > sizeof(key)) {
        return false;
    }
    fill_random_bytes(key, key_len);
    ok = base64_encode(key, key_len, out, out_len);
    secure_zero(key, sizeof(key));
    return ok;
}

static void secure_zero(void *ptr, size_t len) {
    volatile unsigned char *p = ptr;

    while (len > 0) {
        *p++ = 0;
        len--;
    }
}

static int parse_sdp_media_port(const char *message, const char *media, int fallback) {
    const char *pos = strstr(message, media);
    if (pos == NULL) {
        return fallback;
    }
    return atoi(pos + strlen(media));
}

static bool parse_sdp_sdes_key(const char *message, const char *media, unsigned char *out, size_t out_len) {
    const char *section = strstr(message, media);
    const char *section_end;
    unsigned char decoded[64];
    size_t decoded_len = 0;

    if (section == NULL || out == NULL || out_len != MEDIA_SRTP_MASTER_KEY_LEN) {
        return false;
    }
    section_end = strstr(section + strlen(media), "\r\nm=");
    const char *line = section;
    while (line != NULL && *line != '\0' && (section_end == NULL || line < section_end)) {
        const char *line_end = strstr(line, "\r\n");
        if (line_end == NULL) {
            line_end = line + strlen(line);
        }
        if (
            strncasecmp(line, "a=crypto:", strlen("a=crypto:")) == 0
            && strstr(line, "AES_CM_128_HMAC_SHA1_80") != NULL
        ) {
            const char *inline_key = strstr(line, "inline:");
            if (inline_key == NULL || inline_key >= line_end) {
                return false;
            }
            inline_key += strlen("inline:");
            if (!base64_decode(inline_key, decoded, sizeof(decoded), &decoded_len)) {
                return false;
            }
            if (decoded_len < MEDIA_SRTP_MASTER_KEY_LEN) {
                return false;
            }
            memcpy(out, decoded, MEDIA_SRTP_MASTER_KEY_LEN);
            secure_zero(decoded, sizeof(decoded));
            return true;
        }
        if (*line_end == '\0') {
            break;
        }
        line = line_end + 2;
    }
    secure_zero(decoded, sizeof(decoded));
    return false;
}

static int sip_status_code(const char *message) {
    int status = 0;
    if (sscanf(message, "SIP/2.0 %d", &status) != 1) {
        return 0;
    }
    return status;
}

static void cseq_method_value(const char *message, char *out, size_t out_len) {
    char cseq[64];
    header_value(message, "CSeq:", cseq, sizeof(cseq));
    out[0] = '\0';
    char *space = strrchr(cseq, ' ');
    const char *method = space != NULL ? space + 1 : cseq;
    while (*method == ' ' || *method == '\t') {
        method++;
    }
    size_t len = strlen(method);
    while (len > 0 && (method[len - 1] == ' ' || method[len - 1] == '\t' || method[len - 1] == '\r' || method[len - 1] == '\n')) {
        len--;
    }
    if (len >= out_len) {
        len = out_len - 1;
    }
    memcpy(out, method, len);
    out[len] = '\0';
}

static void send_sip_ack(
    int fd,
    const char *from_aor,
    const char *to_aor,
    const char *local_ip,
    uint16_t local_port,
    const char *transport,
    const char *to_header,
    const char *from_tag,
    const char *call_id,
    const char *contact_uri,
    int cseq
) {
    if (
        fd < 0
        || from_aor[0] == '\0'
        || to_aor[0] == '\0'
        || local_ip[0] == '\0'
        || transport[0] == '\0'
        || to_header[0] == '\0'
        || from_tag[0] == '\0'
        || call_id[0] == '\0'
    ) {
        return;
    }
    char fallback_uri[512];
    const char *request_uri = contact_uri != NULL && contact_uri[0] != '\0' ? contact_uri : fallback_uri;
    if (contact_uri == NULL || contact_uri[0] == '\0') {
        if (snprintf(fallback_uri, sizeof(fallback_uri), "sip:%s", to_aor) >= (int)sizeof(fallback_uri)) {
            return;
        }
    }
    char request[1024];
    snprintf(
        request,
        sizeof(request),
        "ACK %s SIP/2.0\r\n"
        "Via: SIP/2.0/%s %s:%u;branch=z9hG4bKack%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: %s\r\n"
        "From: <sip:%s>;tag=%s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: %d ACK\r\n"
        "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
        "Content-Length: 0\r\n\r\n",
        request_uri,
        transport,
        local_ip,
        local_port,
        (long)time(NULL),
        to_header,
        from_aor,
        from_tag,
        call_id,
        cseq
    );
    (void)send_all(fd, request, strlen(request));
}

static void send_sip_ok_response(int fd, const char *message) {
    char to[512];
    char from[512];
    char call_id[128];
    char cseq[64];
    char response[4096];
    size_t used = 0;

    header_value(message, "To:", to, sizeof(to));
    header_value(message, "From:", from, sizeof(from));
    header_value(message, "Call-ID:", call_id, sizeof(call_id));
    header_value(message, "CSeq:", cseq, sizeof(cseq));
    if (to[0] == '\0' || from[0] == '\0' || call_id[0] == '\0' || cseq[0] == '\0') {
        return;
    }

    used += (size_t)snprintf(response + used, sizeof(response) - used, "SIP/2.0 200 OK\r\n");
    append_all_headers(response, sizeof(response), &used, message, "Via:");
    if (used >= sizeof(response)) {
        return;
    }
    (void)c300x_appendf(
        response,
        sizeof(response),
        &used,
        "To: %s\r\n"
        "From: %s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: %s\r\n"
        "Content-Length: 0\r\n\r\n",
        to,
        from,
        call_id,
        cseq
    );
    if (used < sizeof(response)) {
        (void)send_all(fd, response, used);
    }
}

static bool build_ring_sdp(
    char *out,
    size_t out_len,
    const char *from_user,
    const char *audio_key,
    const char *video_key,
    bool audio_active
) {
    int session_id = (int)(time(NULL) % 10000);

    return snprintf(
        out,
        out_len,
        "v=0\r\n"
        "o=%s %d %d IN IP4 127.0.0.1\r\n"
        "s=Talk\r\n"
        "c=IN IP4 127.0.0.1\r\n"
        "b=AS:380\r\n"
        "t=0 0\r\n"
        "a=rtcp-xr:rcvr-rtt=all:10000 stat-summary=loss,dup,jitt,TTL voip-metrics\r\n"
        "m=audio %d RTP/SAVP 96 101\r\n"
        "a=rtpmap:96 speex/8000\r\n"
        "a=fmtp:96 vbr=on\r\n"
        "a=rtpmap:101 telephone-event/8000\r\n"
        "%s"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:%s\r\n"
        "a=rtcp-fb:* trr-int 5000\r\n"
        "a=rtcp-fb:* ccm tmmbr\r\n"
        "m=video %d RTP/SAVP 96\r\n"
        "a=rtpmap:96 H264/90000\r\n"
        "a=fmtp:96 profile-level-id=42801F\r\n"
        "a=recvonly\r\n"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:%s\r\n"
        "a=rtcp-fb:* trr-int 5000\r\n"
        "a=rtcp-fb:* ccm tmmbr\r\n"
        "a=rtcp-fb:96 nack pli\r\n"
        "a=rtcp-fb:96 ccm fir\r\n",
        from_user,
        session_id,
        audio_active ? 2 : 1,
        RING_AUDIO_RTP_PORT,
        audio_active ? "" : "a=inactive\r\n",
        audio_key,
        RING_VIDEO_RTP_PORT,
        video_key
    ) < (int)out_len;
}

static bool send_ring_response(
    media_bridge_t *bridge,
    int fd,
    const char *invite,
    int code,
    const char *reason,
    const char *to_tag,
    const char *from_aor,
    const char *sdp
) {
    char to[512];
    char tagged_to[640];
    char from[512];
    char call_id[128];
    char cseq[64];
    char response[SIP_BUFFER_SIZE];
    char instance_uuid[MEDIA_INSTANCE_UUID_LEN];
    size_t used = 0;

    header_value(invite, "To:", to, sizeof(to));
    header_value(invite, "From:", from, sizeof(from));
    header_value(invite, "Call-ID:", call_id, sizeof(call_id));
    header_value(invite, "CSeq:", cseq, sizeof(cseq));
    if (to[0] == '\0' || from[0] == '\0' || call_id[0] == '\0' || cseq[0] == '\0') {
        return false;
    }
    if (code == 100) {
        snprintf(tagged_to, sizeof(tagged_to), "%s", to);
    } else {
        make_tagged_to(to, to_tag, tagged_to, sizeof(tagged_to));
    }

    used += (size_t)snprintf(response + used, sizeof(response) - used, "SIP/2.0 %d %s\r\n", code, reason);
    append_all_headers(response, sizeof(response), &used, invite, "Via:");
    append_all_headers(response, sizeof(response), &used, invite, "Record-Route:");
    if (used >= sizeof(response)) {
        return false;
    }
    (void)c300x_appendf(
        response,
        sizeof(response),
        &used,
        "From: %s\r\n"
        "To: %s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: %s\r\n",
        from,
        tagged_to,
        call_id,
        cseq
    );
    if (code == 200) {
        if (!bridge_instance_uuid(bridge, bridge->ring_instance_uuid, "ring", instance_uuid, sizeof(instance_uuid))) {
            return false;
        }
        (void)c300x_appendf(
            response,
            sizeof(response),
            &used,
            "Contact: <sip:%s;gr=urn:uuid:%s>;+sip.instance=\"<urn:uuid:%s>\"\r\n"
            "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
            "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE, SUBSCRIBE, INFO, PRACK, UPDATE\r\n"
            "Supported: replaces, outbound, gruu\r\n",
            from_aor,
            instance_uuid,
            instance_uuid
        );
    } else {
        (void)c300x_appendf(
            response,
            sizeof(response),
            &used,
            "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
            "Supported: replaces, outbound, gruu\r\n"
        );
    }
    if (used >= sizeof(response)) {
        return false;
    }
    if (sdp != NULL) {
        (void)c300x_appendf(
            response,
            sizeof(response),
            &used,
            "Content-Type: application/sdp\r\n"
            "Content-Length: %zu\r\n\r\n%s",
            strlen(sdp),
            sdp
        );
    } else {
        (void)c300x_appendf(response, sizeof(response), &used, "Content-Length: 0\r\n\r\n");
    }
    if (used >= sizeof(response)) {
        return false;
    }
    return send_all(fd, response, used) == (ssize_t)used;
}

static bool send_ring_registration(
    media_bridge_t *bridge,
    int fd,
    const char *domain,
    const char *from_aor,
    int cseq,
    int expires
) {
    char request[2048];
    char response[SIP_BUFFER_SIZE];
    char instance_uuid[MEDIA_INSTANCE_UUID_LEN];
    long unique_id = (long)time(NULL) ^ (long)getpid() ^ (long)cseq;
    if (!bridge_instance_uuid(bridge, bridge->ring_instance_uuid, "ring", instance_uuid, sizeof(instance_uuid))) {
        return false;
    }
    int len = snprintf(
        request,
        sizeof(request),
        "REGISTER sip:%s SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:%d;branch=z9hG4bKringreg%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: <sip:%s>\r\n"
        "From: <sip:%s>;tag=ha-ring%ld\r\n"
        "Call-ID: ha-ring-register-%ld\r\n"
        "CSeq: %d REGISTER\r\n"
        "Supported: replaces, outbound, gruu\r\n"
        "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE, SUBSCRIBE, INFO, UPDATE\r\n"
        "Contact: <sip:%s;transport=tcp>;expires=%d;+sip.instance=\"<urn:uuid:%s>\"\r\n"
        "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
        "Expires: %d\r\n"
        "Content-Length: 0\r\n\r\n",
        domain,
        DEFAULT_SIP_PORT,
        unique_id,
        from_aor,
        from_aor,
        unique_id,
        unique_id,
        cseq,
        from_aor,
        expires,
        instance_uuid,
        expires
    );
    if (len <= 0 || len >= (int)sizeof(request)) {
        return false;
    }
    if (send_all(fd, request, (size_t)len) <= 0) {
        return false;
    }
    if (read_message(fd, response, sizeof(response), 3) < 0) {
        return false;
    }
    return sip_status_code(response) >= 200 && sip_status_code(response) < 300;
}

static bool send_ring_register(
    media_bridge_t *bridge,
    int fd,
    const char *domain,
    const char *from_aor,
    int cseq
) {
    return send_ring_registration(bridge, fd, domain, from_aor, cseq, RING_REGISTER_EXPIRES_SECONDS);
}

static void send_ring_unregister(
    media_bridge_t *bridge,
    int fd,
    const char *domain,
    const char *from_aor,
    int cseq
) {
    (void)send_ring_registration(bridge, fd, domain, from_aor, cseq, 0);
}

static void send_ring_bye(
    int fd,
    const char *invite,
    const char *to_tag,
    const char *remote_contact_uri
) {
    char to[512];
    char from[512];
    char call_id[128];
    char tagged_to[640];
    char request[2048];
    const char *request_uri = remote_contact_uri != NULL && remote_contact_uri[0] != '\0'
        ? remote_contact_uri
        : "sip:c300x@127.0.0.1:5060";

    header_value(invite, "To:", to, sizeof(to));
    header_value(invite, "From:", from, sizeof(from));
    header_value(invite, "Call-ID:", call_id, sizeof(call_id));
    make_tagged_to(to, to_tag, tagged_to, sizeof(tagged_to));
    if (tagged_to[0] == '\0' || from[0] == '\0' || call_id[0] == '\0') {
        return;
    }
    snprintf(
        request,
        sizeof(request),
        "BYE %s SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:%d;branch=z9hG4bKringbye%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "From: %s\r\n"
        "To: %s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: 111 BYE\r\n"
        "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
        "Content-Length: 0\r\n\r\n",
        request_uri,
        DEFAULT_SIP_PORT,
        (long)time(NULL),
        tagged_to,
        from,
        call_id
    );
    (void)send_all(fd, request, strlen(request));
}

static void forward_rtsp_packet(media_bridge_t *bridge, const unsigned char *packet, int packet_len, bool audio) {
    rtsp_send_target_t targets[C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS];
    size_t target_count;

    if (bridge == NULL || packet == NULL || packet_len <= 0) {
        return;
    }
    pthread_mutex_lock(&bridge->mutex);
    target_count = rtsp_send_targets_locked(bridge, audio, targets, C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS);
    pthread_mutex_unlock(&bridge->mutex);

    if (target_count == 0) {
        return;
    }
    c300x_video_bridge_rtp_packet(bridge->video);
    for (size_t index = 0; index < target_count; index++) {
        const rtsp_send_target_t *target = &targets[index];
        if (target->transport_tcp) {
            unsigned char frame_header[4];
            frame_header[0] = '$';
            frame_header[1] = (unsigned char)target->channel;
            frame_header[2] = (unsigned char)(((unsigned)packet_len >> 8) & 0xff);
            frame_header[3] = (unsigned char)((unsigned)packet_len & 0xff);
            if (
                send_all(target->fd, frame_header, sizeof(frame_header)) <= 0
                || send_all(target->fd, packet, (size_t)packet_len) <= 0
            ) {
                shutdown(target->fd, SHUT_RDWR);
            }
        } else {
            (void)sendto(
                target->fd,
                packet,
                (size_t)packet_len,
                0,
                (struct sockaddr *)&target->udp_client,
                sizeof(target->udp_client)
            );
        }
    }
}

static bool rtp_payload_offset(const unsigned char *packet, int packet_len, size_t *payload_offset) {
    size_t header_len;

    if (packet == NULL || payload_offset == NULL || packet_len < 12 || (packet[0] & 0xc0) != 0x80) {
        return false;
    }
    header_len = 12 + ((size_t)(packet[0] & 0x0f) * 4);
    if ((size_t)packet_len < header_len) {
        return false;
    }
    if ((packet[0] & 0x10) != 0) {
        uint16_t extension_words;
        if ((size_t)packet_len < header_len + 4) {
            return false;
        }
        extension_words = load_be16(packet + header_len + 2);
        header_len += 4 + ((size_t)extension_words * 4);
        if ((size_t)packet_len < header_len) {
            return false;
        }
    }
    *payload_offset = header_len;
    return true;
}

static bool rtsp_audio_payload_is_speex_8khz(unsigned char payload_type) {
    return payload_type == RING_AUDIO_PAYLOAD_TYPE
        || payload_type == MEDIA_AUDIO_PAYLOAD_TYPE;
}

static bool next_rtsp_audio_output_timestamp(
    media_bridge_t *bridge,
    const unsigned char *source_packet,
    size_t sample_count,
    uint16_t *sequence,
    uint32_t *timestamp
) {
    if (
        bridge == NULL
        || source_packet == NULL
        || sample_count == 0
        || sequence == NULL
        || timestamp == NULL
    ) {
        return false;
    }

    pthread_mutex_lock(&bridge->mutex);
    if (!bridge->rtsp_audio_out_initialized) {
        bridge->rtsp_audio_out_seq = load_be16(source_packet + 2);
        bridge->rtsp_audio_out_timestamp = load_be32(source_packet + 4);
        bridge->rtsp_audio_out_initialized = true;
    }
    *sequence = bridge->rtsp_audio_out_seq++;
    *timestamp = bridge->rtsp_audio_out_timestamp;
    bridge->rtsp_audio_out_timestamp += (uint32_t)sample_count;
    pthread_mutex_unlock(&bridge->mutex);
    return true;
}

static bool forward_rtsp_audio_pcmu_payload(
    media_bridge_t *bridge,
    const unsigned char *source_packet,
    const unsigned char *payload,
    size_t payload_len,
    bool marker
) {
    unsigned char out[12 + RTSP_AUDIO_FRAME_SAMPLES];
    size_t offset = 0;

    if (
        bridge == NULL
        || source_packet == NULL
        || payload == NULL
        || payload_len == 0
    ) {
        return false;
    }

    while (offset < payload_len) {
        uint16_t sequence;
        uint32_t timestamp;
        size_t take = payload_len - offset;
        if (take > RTSP_AUDIO_FRAME_SAMPLES) {
            take = RTSP_AUDIO_FRAME_SAMPLES;
        }
        if (!next_rtsp_audio_output_timestamp(bridge, source_packet, take, &sequence, &timestamp)) {
            return false;
        }

        memset(out, 0, sizeof(out));
        out[0] = 0x80;
        out[1] = (unsigned char)(
            ((offset + take >= payload_len && marker) ? 0x80 : 0)
            | RTSP_AUDIO_PAYLOAD_TYPE
        );
        store_be16(out + 2, sequence);
        store_be32(out + 4, timestamp);
        memcpy(out + 8, source_packet + 8, 4);
        memcpy(out + 12, payload + offset, take);
        forward_rtsp_packet(bridge, out, (int)(12 + take), true);
        offset += take;
    }
    return true;
}

static bool forward_rtsp_audio_pcmu_packet(
    media_bridge_t *bridge,
    const unsigned char *packet,
    int packet_len
) {
    unsigned char payload_type;
    size_t payload_offset;
    size_t payload_len;
    int16_t samples[RTSP_AUDIO_FRAME_SAMPLES];
    unsigned char pcmu_payload[RTSP_AUDIO_FRAME_SAMPLES];
    bool marker;

    if (!rtp_payload_offset(packet, packet_len, &payload_offset) || (size_t)packet_len <= payload_offset) {
        return false;
    }

    payload_type = packet[1] & 0x7f;
    payload_len = (size_t)packet_len - payload_offset;
    marker = (packet[1] & 0x80) != 0;
    if (payload_type == RTSP_BACKCHANNEL_PCMU_PAYLOAD_TYPE) {
        return forward_rtsp_audio_pcmu_payload(
            bridge,
            packet,
            packet + payload_offset,
            payload_len,
            marker
        );
    }
    if (payload_type == RTSP_BACKCHANNEL_PCMA_PAYLOAD_TYPE) {
        size_t offset = 0;
        while (offset < payload_len) {
            size_t take = payload_len - offset;
            if (take > RTSP_AUDIO_FRAME_SAMPLES) {
                take = RTSP_AUDIO_FRAME_SAMPLES;
            }
            for (size_t index = 0; index < take; index++) {
                pcmu_payload[index] = encode_pcmu_sample(
                    decode_pcma_sample(packet[payload_offset + offset + index])
                );
            }
            if (!forward_rtsp_audio_pcmu_payload(
                bridge,
                packet,
                pcmu_payload,
                take,
                offset + take >= payload_len && marker
            )) {
                return false;
            }
            offset += take;
        }
        return true;
    }
    if (!rtsp_audio_payload_is_speex_8khz(payload_type)) {
        return false;
    }
    if (!speex_decode_audio_frame(packet + payload_offset, payload_len, samples, RTSP_AUDIO_FRAME_SAMPLES)) {
        return false;
    }

    for (size_t index = 0; index < RTSP_AUDIO_FRAME_SAMPLES; index++) {
        pcmu_payload[index] = encode_pcmu_sample(samples[index]);
    }
    return forward_rtsp_audio_pcmu_payload(
        bridge,
        packet,
        pcmu_payload,
        sizeof(pcmu_payload),
        marker
    );
}

static void drain_ring_srtp_socket(
    media_bridge_t *bridge,
    int fd,
    c300x_srtp_t session,
    bool rtcp,
    bool audio,
    uint32_t *video_ssrc
) {
    c300x_srtp_api_t *api = srtp_api();
    unsigned char packet[2048];
    struct sockaddr_in from;
    socklen_t from_len = sizeof(from);
    ssize_t n;

    if (api == NULL || fd < 0 || session == NULL) {
        return;
    }
    while ((n = recvfrom(fd, packet, sizeof(packet), MSG_DONTWAIT, (struct sockaddr *)&from, &from_len)) > 0) {
        int packet_len = (int)n;
        int ok = rtcp
            ? api->srtp_unprotect_rtcp(session, packet, &packet_len) == 0
            : api->srtp_unprotect(session, packet, &packet_len) == 0;
        if (ok && !rtcp) {
            if (audio) {
                (void)forward_rtsp_audio_pcmu_packet(bridge, packet, packet_len);
                from_len = sizeof(from);
                continue;
            }
            if (!audio && video_ssrc != NULL && packet_len >= 12 && (packet[0] & 0xc0) == 0x80) {
                *video_ssrc = ((uint32_t)packet[8] << 24)
                    | ((uint32_t)packet[9] << 16)
                    | ((uint32_t)packet[10] << 8)
                    | (uint32_t)packet[11];
            }
            forward_rtsp_packet(bridge, packet, packet_len, audio);
        }
        from_len = sizeof(from);
    }
}

static bool ring_call_active_locked(const media_bridge_t *bridge) {
    return bridge->ring_call_active && !bridge->ring_call_stop;
}

static bool request_ring_answer_if_active(media_bridge_t *bridge) {
    bool active;
    struct timespec deadline;

    pthread_mutex_lock(&bridge->mutex);
    active = ring_call_active_locked(bridge);
    if (active && !bridge->ring_answered) {
        bridge->ring_answer_requested = true;
        pthread_cond_broadcast(&bridge->ready_cond);
        clock_gettime(CLOCK_REALTIME, &deadline);
        deadline.tv_sec += 2;
        while (
            bridge->ring_call_active
            && !bridge->ring_call_stop
            && !bridge->ring_answered
        ) {
            if (pthread_cond_timedwait(&bridge->ready_cond, &bridge->mutex, &deadline) == ETIMEDOUT) {
                break;
            }
        }
    }
    pthread_mutex_unlock(&bridge->mutex);
    return active;
}

static bool ring_session_active(media_bridge_t *bridge) {
    bool active;

    pthread_mutex_lock(&bridge->mutex);
    active = ring_call_active_locked(bridge);
    pthread_mutex_unlock(&bridge->mutex);
    return active;
}

static bool wait_for_ring_session_active(media_bridge_t *bridge, int timeout_ms) {
    bool active = false;
    long long deadline = monotonic_ms() + timeout_ms;

    while (monotonic_ms() < deadline) {
        if (ring_session_active(bridge)) {
            return true;
        }
        usleep(50000);
    }
    active = ring_session_active(bridge);
    return active;
}

static bool home_call_active_locked(const media_bridge_t *bridge) {
    return (bridge->home_call_started || bridge->home_call_active) && !bridge->home_call_stop;
}

static bool doorbell_media_session_active_locked(const media_bridge_t *bridge) {
    return (
        !bridge->stop_in_progress
        && !home_call_active_locked(bridge)
        && (
            bridge->media_active
            || bridge->media_starting
            || bridge->relay_started
            || bridge->sip_monitor_started
            || bridge->ondemand_media_started
            || bridge->talkback_started
            || bridge->rtp_fd >= 0
            || bridge->audio_rtp_fd >= 0
            || bridge->ondemand_audio_rtp_fd >= 0
            || bridge->ondemand_audio_rtcp_fd >= 0
            || bridge->ondemand_video_rtp_fd >= 0
            || bridge->ondemand_video_rtcp_fd >= 0
            || bridge->sip_fd >= 0
            || bridge->talkback_fd >= 0
        )
    );
}

static bool request_home_call_media_if_active(media_bridge_t *bridge, bool audio) {
    bool active;

    (void)audio;
    pthread_mutex_lock(&bridge->mutex);
    active = home_call_active_locked(bridge);
    pthread_mutex_unlock(&bridge->mutex);
    return active;
}

static bool stop_ring_call_if_active(bool send_bye, bool close_client) {
    bool active;

    pthread_mutex_lock(&g_bridge.mutex);
    active = (g_bridge.ring_call_active || g_bridge.ring_media_active) && !g_bridge.ring_call_stop;
    if (active) {
        g_bridge.ring_call_stop = true;
        g_bridge.ring_send_bye = g_bridge.ring_send_bye || send_bye;
    }
    if (active && close_client) {
        shutdown_all_rtsp_clients_locked(&g_bridge);
    }
    pthread_mutex_unlock(&g_bridge.mutex);
    return active;
}

static void close_ring_media_fds_locked(media_bridge_t *bridge) {
    close_fd_if_open(&bridge->ring_audio_rtp_fd);
    close_fd_if_open(&bridge->ring_audio_rtcp_fd);
    close_fd_if_open(&bridge->ring_video_rtp_fd);
    close_fd_if_open(&bridge->ring_video_rtcp_fd);
}

static void ring_call_cleanup(media_bridge_t *bridge) {
    bool was_active;

    pthread_mutex_lock(&bridge->mutex);
    was_active = (
        bridge->ring_call_active
        || bridge->ring_media_active
        || bridge->ring_answered
        || bridge->ring_answer_requested
    );
    close_ring_media_fds_locked(bridge);
    bridge->ring_call_active = false;
    bridge->ring_media_active = false;
    bridge->ring_audio_active = false;
    bridge->ring_answered = false;
    bridge->ring_answer_requested = false;
    bridge->ring_call_stop = false;
    bridge->ring_send_bye = false;
    bridge->ring_target_audio_port = 0;
    bridge->ring_target_video_port = 0;
    bridge->ring_last_talkback_ms = 0;
    bridge->ring_srtp_state = NULL;
    reset_backchannel_talkback_locked(bridge);
    pthread_mutex_unlock(&bridge->mutex);
    c300x_video_bridge_media_stopped(bridge->video);
    if (was_active && c300x_video_consume_media_closed_event(bridge->video)) {
        c300x_video_dispatch_event(bridge->video, "doorbell.media.closed", "{}", 0);
    }
}

static void ring_media_loop(
    media_bridge_t *bridge,
    int sip_fd,
    const char *invite,
    const char *to_tag,
    const char *from_aor,
    const char *sdp_answer,
    const char *remote_contact_uri,
    media_srtp_state_t *srtp
) {
    long long next_audio = 0;
    long long next_rtcp = 0;
    long long next_stun = 0;
    long long started_at = monotonic_ms();
    long long last_inbound_activity = started_at;
    long long next_sip_keepalive = started_at + ((long long)MEDIA_SIP_KEEPALIVE_SECONDS * 1000LL);
    uint32_t video_ssrc = 0;
    char message[SIP_BUFFER_SIZE];
    bool remote_ended = false;

    while (!remote_ended) {
        bool stop;
        bool send_bye;
        bool answer_requested;
        bool answered;
        int audio_fd;
        int audio_rtcp_fd;
        int video_fd;
        int video_rtcp_fd;
        int target_audio_port;
        int target_video_port;
        int rtsp_clients;

        pthread_mutex_lock(&bridge->mutex);
        stop = bridge->ring_call_stop || bridge->ring_stop;
        send_bye = bridge->ring_send_bye;
        answer_requested = bridge->ring_answer_requested;
        answered = bridge->ring_answered;
        audio_fd = bridge->ring_audio_rtp_fd;
        audio_rtcp_fd = bridge->ring_audio_rtcp_fd;
        video_fd = bridge->ring_video_rtp_fd;
        video_rtcp_fd = bridge->ring_video_rtcp_fd;
        target_audio_port = bridge->ring_target_audio_port;
        target_video_port = bridge->ring_target_video_port;
        rtsp_clients = rtsp_client_count_locked(bridge);
        pthread_mutex_unlock(&bridge->mutex);

        if (stop) {
            if (send_bye) {
                send_ring_bye(sip_fd, invite, to_tag, remote_contact_uri);
            }
            break;
        }

        if (answer_requested && !answered) {
            if (!send_ring_response(bridge, sip_fd, invite, 200, "Ok", to_tag, from_aor, sdp_answer)) {
                break;
            }
            pthread_mutex_lock(&bridge->mutex);
            bridge->ring_answered = true;
            bridge->ring_audio_active = true;
            bridge->ring_answer_requested = false;
            pthread_cond_broadcast(&bridge->ready_cond);
            pthread_mutex_unlock(&bridge->mutex);
            c300x_video_bridge_ring_media_started(bridge->video, 1);
            c300x_video_dispatch_event(bridge->video, "doorbell.view_requested", "{}", 0);
            answered = true;
            last_inbound_activity = monotonic_ms();
        }

        fd_set readfds;
        FD_ZERO(&readfds);
        int max_fd = sip_fd;
        FD_SET(sip_fd, &readfds);
        if (audio_fd >= 0) {
            FD_SET(audio_fd, &readfds);
            max_fd = audio_fd > max_fd ? audio_fd : max_fd;
        }
        if (audio_rtcp_fd >= 0) {
            FD_SET(audio_rtcp_fd, &readfds);
            max_fd = audio_rtcp_fd > max_fd ? audio_rtcp_fd : max_fd;
        }
        if (video_fd >= 0) {
            FD_SET(video_fd, &readfds);
            max_fd = video_fd > max_fd ? video_fd : max_fd;
        }
        if (video_rtcp_fd >= 0) {
            FD_SET(video_rtcp_fd, &readfds);
            max_fd = video_rtcp_fd > max_fd ? video_rtcp_fd : max_fd;
        }

        struct timeval timeout = {0, MEDIA_AUDIO_PACKET_MS * 1000};
        int ready = select(max_fd + 1, &readfds, NULL, NULL, &timeout);
        if (ready > 0) {
            if (FD_ISSET(sip_fd, &readfds)) {
                int n = read_message(sip_fd, message, sizeof(message), 1);
                if (n < 0) {
                    break;
                }
                if (n > 0 && strncmp(message, "\r\n\r\n", 4) != 0) {
                    last_inbound_activity = monotonic_ms();
                    if (strncmp(message, "BYE ", 4) == 0 || strncmp(message, "CANCEL ", 7) == 0) {
                        send_sip_ok_response(sip_fd, message);
                        remote_ended = true;
                    } else if (strncmp(message, "OPTIONS ", 8) == 0 || strncmp(message, "NOTIFY ", 7) == 0) {
                        send_sip_ok_response(sip_fd, message);
                    }
                }
            }
            if (audio_fd >= 0 && FD_ISSET(audio_fd, &readfds)) {
                last_inbound_activity = monotonic_ms();
                drain_ring_srtp_socket(bridge, audio_fd, srtp->audio_in, false, true, NULL);
            }
            if (audio_rtcp_fd >= 0 && FD_ISSET(audio_rtcp_fd, &readfds)) {
                last_inbound_activity = monotonic_ms();
                drain_ring_srtp_socket(bridge, audio_rtcp_fd, srtp->audio_in, true, true, NULL);
            }
            if (video_fd >= 0 && FD_ISSET(video_fd, &readfds)) {
                last_inbound_activity = monotonic_ms();
                drain_ring_srtp_socket(bridge, video_fd, srtp->video_in, false, false, &video_ssrc);
            }
            if (video_rtcp_fd >= 0 && FD_ISSET(video_rtcp_fd, &readfds)) {
                last_inbound_activity = monotonic_ms();
                drain_ring_srtp_socket(bridge, video_rtcp_fd, srtp->video_in, true, false, NULL);
            }
        }

        long long now = monotonic_ms();
        if (
            (!answered || rtsp_clients <= 0)
            &&
            now - last_inbound_activity >= (
                answered
                    ? RING_ANSWERED_MEDIA_IDLE_TIMEOUT_MS
                    : RING_UNANSWERED_MEDIA_IDLE_TIMEOUT_MS
            )
        ) {
            break;
        }
        if (now >= next_sip_keepalive) {
            (void)send_all(sip_fd, "\r\n\r\n", 4);
            next_sip_keepalive = now + ((long long)MEDIA_SIP_KEEPALIVE_SECONDS * 1000LL);
        }
        if (answered && (next_stun == 0 || now >= next_stun)) {
            send_stun_binding_request(audio_fd, target_audio_port);
            send_stun_binding_request(audio_rtcp_fd, target_audio_port + 1);
            send_stun_binding_request(video_fd, target_video_port);
            send_stun_binding_request(video_rtcp_fd, target_video_port + 1);
            next_stun = now + MEDIA_KEEPALIVE_MS;
        }
        if (answered && (next_audio == 0 || now >= next_audio)) {
            pthread_mutex_lock(&bridge->mutex);
            if (bridge->ring_srtp_state == srtp) {
                if (!send_queued_talkback_payload_locked(
                    bridge,
                    audio_fd,
                    target_audio_port,
                    srtp,
                    RING_AUDIO_PAYLOAD_TYPE,
                    &bridge->ring_last_talkback_ms
                ) && !ring_talkback_recent_locked(bridge, now)) {
                    send_media_audio_silence_payload_type(
                        audio_fd,
                        target_audio_port,
                        srtp,
                        RING_AUDIO_PAYLOAD_TYPE
                    );
                }
            }
            pthread_mutex_unlock(&bridge->mutex);
            next_audio = now + MEDIA_AUDIO_PACKET_MS;
        }
        if (answered && (next_rtcp == 0 || now >= next_rtcp)) {
            pthread_mutex_lock(&bridge->mutex);
            if (bridge->ring_srtp_state == srtp) {
                send_srtcp_receiver_report(audio_rtcp_fd, target_audio_port + 1, srtp->audio, srtp->audio_ssrc);
                send_srtcp_receiver_report(video_rtcp_fd, target_video_port + 1, srtp->video, srtp->rtcp_sender_ssrc);
                if (video_ssrc != 0) {
                    send_srtcp_pli(video_rtcp_fd, target_video_port + 1, srtp->video, srtp->rtcp_sender_ssrc, video_ssrc);
                }
            }
            pthread_mutex_unlock(&bridge->mutex);
            next_rtcp = now + 1000;
        }
    }
}

static void handle_ring_invite(
    media_bridge_t *bridge,
    int sip_fd,
    const char *invite,
    const char *from_user,
    const char *from_aor
) {
    int audio_fd = -1;
    int audio_rtcp_fd = -1;
    int video_fd = -1;
    int video_rtcp_fd = -1;
    unsigned char answer_audio_key_raw[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char answer_video_key_raw[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char offer_audio_key_raw[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char offer_video_key_raw[MEDIA_SRTP_MASTER_KEY_LEN];
    char answer_audio_key[64];
    char answer_video_key[64];
    char sdp_early[4096];
    char sdp_answer[4096];
    char to_tag[64];
    char remote_contact[512];
    char remote_contact_uri[512];
    media_srtp_state_t srtp;
    bool srtp_ready = false;

    memset(&srtp, 0, sizeof(srtp));
    audio_fd = bind_udp_loopback_port(RING_AUDIO_RTP_PORT);
    audio_rtcp_fd = bind_udp_loopback_port(RING_AUDIO_RTCP_PORT);
    video_fd = bind_udp_loopback_port(RING_VIDEO_RTP_PORT);
    video_rtcp_fd = bind_udp_loopback_port(RING_VIDEO_RTCP_PORT);
    if (audio_fd < 0 || audio_rtcp_fd < 0 || video_fd < 0 || video_rtcp_fd < 0) {
        goto cleanup;
    }
    if (
        !parse_sdp_sdes_key(invite, "\r\nm=audio ", offer_audio_key_raw, sizeof(offer_audio_key_raw))
        || !parse_sdp_sdes_key(invite, "\r\nm=video ", offer_video_key_raw, sizeof(offer_video_key_raw))
        || !generate_sdes_key(answer_audio_key_raw, sizeof(answer_audio_key_raw), answer_audio_key, sizeof(answer_audio_key))
        || !generate_sdes_key(answer_video_key_raw, sizeof(answer_video_key_raw), answer_video_key, sizeof(answer_video_key))
        || !media_srtp_init_state(&srtp, answer_audio_key_raw, answer_video_key_raw)
        || !media_srtp_init_inbound(&srtp, offer_audio_key_raw, offer_video_key_raw)
    ) {
        goto cleanup;
    }
    srtp_ready = true;
    if (
        !build_ring_sdp(sdp_early, sizeof(sdp_early), from_user, answer_audio_key, answer_video_key, false)
        || !build_ring_sdp(sdp_answer, sizeof(sdp_answer), from_user, answer_audio_key, answer_video_key, true)
    ) {
        goto cleanup;
    }

    snprintf(to_tag, sizeof(to_tag), "ha-ring%ld", (long)time(NULL));
    header_value(invite, "Contact:", remote_contact, sizeof(remote_contact));
    sip_uri_from_header(remote_contact, remote_contact_uri, sizeof(remote_contact_uri));

    pthread_mutex_lock(&bridge->mutex);
    close_ring_media_fds_locked(bridge);
    bridge->ring_audio_rtp_fd = audio_fd;
    bridge->ring_audio_rtcp_fd = audio_rtcp_fd;
    bridge->ring_video_rtp_fd = video_fd;
    bridge->ring_video_rtcp_fd = video_rtcp_fd;
    bridge->ring_target_audio_port = parse_sdp_media_port(invite, "\r\nm=audio ", 7078);
    bridge->ring_target_video_port = parse_sdp_media_port(invite, "\r\nm=video ", 9078);
    bridge->ring_call_active = true;
    bridge->ring_media_active = false;
    bridge->ring_audio_active = false;
    bridge->ring_answered = false;
    bridge->ring_answer_requested = false;
    bridge->ring_call_stop = false;
    bridge->ring_send_bye = false;
    bridge->ring_last_talkback_ms = 0;
    reset_backchannel_talkback_locked(bridge);
    bridge->ring_srtp_state = srtp_ready ? &srtp : NULL;
    pthread_mutex_unlock(&bridge->mutex);
    audio_fd = -1;
    audio_rtcp_fd = -1;
    video_fd = -1;
    video_rtcp_fd = -1;
    if (!start_talkback_proxy(bridge)) {
        c300x_video_bridge_set_error(bridge->video, "ring_talkback_start_failed");
    }

    if (!send_ring_response(bridge, sip_fd, invite, 100, "Trying", to_tag, from_aor, NULL)) {
        goto cleanup;
    }
    if (!send_ring_response(bridge, sip_fd, invite, 180, "Ringing", to_tag, from_aor, NULL)) {
        goto cleanup;
    }
    struct timespec early_delay = {0, RING_EARLY_MEDIA_DELAY_MS * 1000000L};
    (void)nanosleep(&early_delay, NULL);
    if (!send_ring_response(bridge, sip_fd, invite, 183, "Session progress", to_tag, from_aor, sdp_early)) {
        goto cleanup;
    }

    pthread_mutex_lock(&bridge->mutex);
    bridge->ring_media_active = true;
    pthread_mutex_unlock(&bridge->mutex);
    c300x_video_bridge_ring_media_started(bridge->video, 0);

    ring_media_loop(
        bridge,
        sip_fd,
        invite,
        to_tag,
        from_aor,
        sdp_answer,
        remote_contact_uri,
        &srtp
    );

cleanup:
    pthread_mutex_lock(&bridge->mutex);
    if (bridge->ring_srtp_state == &srtp) {
        bridge->ring_srtp_state = NULL;
        reset_backchannel_talkback_locked(bridge);
    }
    pthread_mutex_unlock(&bridge->mutex);
    if (audio_fd >= 0) {
        close(audio_fd);
    }
    if (audio_rtcp_fd >= 0) {
        close(audio_rtcp_fd);
    }
    if (video_fd >= 0) {
        close(video_fd);
    }
    if (video_rtcp_fd >= 0) {
        close(video_rtcp_fd);
    }
    if (srtp_ready) {
        media_srtp_deinit_state(&srtp);
    }
    secure_zero(answer_audio_key_raw, sizeof(answer_audio_key_raw));
    secure_zero(answer_video_key_raw, sizeof(answer_video_key_raw));
    secure_zero(offer_audio_key_raw, sizeof(offer_audio_key_raw));
    secure_zero(offer_video_key_raw, sizeof(offer_video_key_raw));
    ring_call_cleanup(bridge);
}

static bool ring_sleep_seconds(media_bridge_t *bridge, int seconds) {
    for (int elapsed = 0; elapsed < seconds; elapsed++) {
        bool stop;
        struct timespec delay = {1, 0};

        pthread_mutex_lock(&bridge->mutex);
        stop = bridge->ring_stop;
        pthread_mutex_unlock(&bridge->mutex);
        if (stop) {
            return false;
        }
        (void)nanosleep(&delay, NULL);
    }
    return true;
}

static void *ring_receiver_thread(void *arg) {
    media_bridge_t *bridge = arg;
    char *message = malloc(SIP_BUFFER_SIZE);
    int register_cseq = 20;

    if (message == NULL) {
        c300x_video_bridge_set_error(bridge->video, "ring_receiver_out_of_memory");
        pthread_mutex_lock(&bridge->mutex);
        bridge->ring_started = false;
        bridge->ring_registered = false;
        bridge->ring_sip_fd = -1;
        pthread_mutex_unlock(&bridge->mutex);
        return NULL;
    }

    while (true) {
        bool stop;
        char domain[128];
        char domain_hint[128] = "";
        char from_user[128];
        char from_aor[256];
        char to_aor[256];
        int fd;
        long long next_keepalive;
        long long next_register;

        pthread_mutex_lock(&bridge->mutex);
        stop = bridge->ring_stop;
        pthread_mutex_unlock(&bridge->mutex);
        if (stop) {
            break;
        }
        (void)sip_domain_from_config(bridge->config, domain_hint, sizeof(domain_hint));
        if (
            !media_identity_from_flexisip(
                domain_hint,
                domain,
                sizeof(domain),
                from_user,
                sizeof(from_user),
                from_aor,
                sizeof(from_aor),
                to_aor,
                sizeof(to_aor)
            )
            || srtp_api() == NULL
        ) {
            if (!ring_sleep_seconds(bridge, RING_RETRY_SECONDS)) {
                break;
            }
            continue;
        }
        fd = connect_sip_socket(bridge->config);
        if (fd < 0) {
            if (!ring_sleep_seconds(bridge, RING_RETRY_SECONDS)) {
                break;
            }
            continue;
        }
        if (!send_ring_register(bridge, fd, domain, from_aor, register_cseq++)) {
            close(fd);
            if (!ring_sleep_seconds(bridge, RING_RETRY_SECONDS)) {
                break;
            }
            continue;
        }

        pthread_mutex_lock(&bridge->mutex);
        bridge->ring_registered = true;
        bridge->ring_sip_fd = fd;
        pthread_mutex_unlock(&bridge->mutex);
        next_keepalive = monotonic_ms() + ((long long)MEDIA_SIP_KEEPALIVE_SECONDS * 1000LL);
        next_register = monotonic_ms() + ((long long)RING_REGISTER_RENEW_SECONDS * 1000LL);

        while (true) {
            pthread_mutex_lock(&bridge->mutex);
            stop = bridge->ring_stop;
            pthread_mutex_unlock(&bridge->mutex);
            if (stop) {
                break;
            }
            int n = read_message_poll(fd, message, SIP_BUFFER_SIZE, 1);
            if (n < 0) {
                break;
            }
            if (n > 0 && strncmp(message, "\r\n\r\n", 4) != 0) {
                if (strncmp(message, "INVITE ", 7) == 0 && strstr(message, "sip:alluser@") != NULL) {
                    handle_ring_invite(bridge, fd, message, from_user, from_aor);
                } else if (strncmp(message, "OPTIONS ", 8) == 0 || strncmp(message, "NOTIFY ", 7) == 0) {
                    send_sip_ok_response(fd, message);
                }
            }

            long long now = monotonic_ms();
            if (now >= next_keepalive) {
                (void)send_all(fd, "\r\n\r\n", 4);
                next_keepalive = now + ((long long)MEDIA_SIP_KEEPALIVE_SECONDS * 1000LL);
            }
            if (now >= next_register) {
                if (!send_ring_register(bridge, fd, domain, from_aor, register_cseq++)) {
                    break;
                }
                next_register = now + ((long long)RING_REGISTER_RENEW_SECONDS * 1000LL);
            }
        }

        pthread_mutex_lock(&bridge->mutex);
        bool was_registered = bridge->ring_registered && bridge->ring_sip_fd == fd;
        pthread_mutex_unlock(&bridge->mutex);
        if (was_registered) {
            send_ring_unregister(bridge, fd, domain, from_aor, register_cseq++);
        }
        pthread_mutex_lock(&bridge->mutex);
        if (bridge->ring_sip_fd == fd) {
            bridge->ring_sip_fd = -1;
        }
        bridge->ring_registered = false;
        pthread_mutex_unlock(&bridge->mutex);
        shutdown(fd, SHUT_RDWR);
        close(fd);
        if (!ring_sleep_seconds(bridge, RING_RETRY_SECONDS)) {
            break;
        }
    }

    pthread_mutex_lock(&bridge->mutex);
    bridge->ring_started = false;
    bridge->ring_registered = false;
    bridge->ring_sip_fd = -1;
    pthread_mutex_unlock(&bridge->mutex);
    secure_zero(message, SIP_BUFFER_SIZE);
    free(message);
    return NULL;
}

static void *sip_monitor_thread(void *arg) {
    media_bridge_t *bridge = arg;
    char message[SIP_BUFFER_SIZE];

    while (true) {
        int fd;
        bool stop;
        char from_aor[256];
        char to_aor[256];
        char local_ip[64];
        char transport[4];
        uint16_t local_port;
        char call_id[128];
        char from_tag[64];
        char to_header[512];
        char contact_uri[512];
        int invite_cseq;

        pthread_mutex_lock(&bridge->mutex);
        fd = bridge->sip_fd;
        stop = bridge->sip_stop;
        snprintf(from_aor, sizeof(from_aor), "%s", bridge->from_aor);
        snprintf(to_aor, sizeof(to_aor), "%s", bridge->to_aor);
        snprintf(local_ip, sizeof(local_ip), "%s", bridge->sip_local_ip);
        snprintf(transport, sizeof(transport), "%s", bridge->sip_transport);
        local_port = bridge->sip_local_port;
        snprintf(call_id, sizeof(call_id), "%s", bridge->call_id);
        snprintf(from_tag, sizeof(from_tag), "%s", bridge->from_tag);
        snprintf(to_header, sizeof(to_header), "%s", bridge->to_header);
        snprintf(contact_uri, sizeof(contact_uri), "%s", bridge->contact_uri);
        invite_cseq = bridge->invite_cseq;
        pthread_mutex_unlock(&bridge->mutex);

        if (stop || fd < 0) {
            break;
        }

        int n = read_message_poll(fd, message, sizeof(message), 1);
        if (n < 0) {
            break;
        }
        if (n == 0) {
            continue;
        }

        char cseq_method[16];
        cseq_method_value(message, cseq_method, sizeof(cseq_method));
        if (sip_status_code(message) == 200 && strcmp(cseq_method, "INVITE") == 0) {
            send_sip_ack(fd, from_aor, to_aor, local_ip, local_port, transport, to_header, from_tag, call_id, contact_uri, invite_cseq);
            continue;
        }

        char method[16] = {0};
        (void)sscanf(message, "%15s", method);
        if (strcmp(method, "BYE") == 0) {
            send_sip_ok_response(fd, message);
            pthread_mutex_lock(&bridge->mutex);
            bridge->relay_stop = true;
            shutdown_all_rtsp_clients_locked(bridge);
            pthread_mutex_unlock(&bridge->mutex);
            break;
        }
    }

    pthread_mutex_lock(&bridge->mutex);
    bridge->sip_monitor_started = false;
    pthread_mutex_unlock(&bridge->mutex);
    return NULL;
}

static void send_udp_loopback(int fd, int port, const unsigned char *data, size_t len) {
    struct sockaddr_in target;

    if (fd < 0 || port <= 0) {
        return;
    }
    memset(&target, 0, sizeof(target));
    target.sin_family = AF_INET;
    target.sin_port = htons((uint16_t)port);
    (void)inet_pton(AF_INET, "127.0.0.1", &target.sin_addr);
    (void)sendto(fd, data, len, 0, (struct sockaddr *)&target, sizeof(target));
}

static void send_stun_binding_request(int fd, int port) {
    unsigned char packet[20] = {
        0x00, 0x01, 0x00, 0x00,
        0x21, 0x12, 0xa4, 0x42,
    };

    fill_random_bytes(packet + 8, sizeof(packet) - 8);
    send_udp_loopback(fd, port, packet, sizeof(packet));
}

static void store_be16(unsigned char *out, uint16_t value) {
    out[0] = (unsigned char)((value >> 8) & 0xff);
    out[1] = (unsigned char)(value & 0xff);
}

static uint16_t load_be16(const unsigned char *in) {
    return (uint16_t)(((uint16_t)in[0] << 8) | in[1]);
}

static uint32_t load_be32(const unsigned char *in) {
    return ((uint32_t)in[0] << 24)
        | ((uint32_t)in[1] << 16)
        | ((uint32_t)in[2] << 8)
        | (uint32_t)in[3];
}

static void store_be32(unsigned char *out, uint32_t value) {
    out[0] = (unsigned char)((value >> 24) & 0xff);
    out[1] = (unsigned char)((value >> 16) & 0xff);
    out[2] = (unsigned char)((value >> 8) & 0xff);
    out[3] = (unsigned char)(value & 0xff);
}

static int protect_and_send_srtp(c300x_srtp_t session, int fd, int port, unsigned char *packet, int packet_len) {
    c300x_srtp_api_t *api = srtp_api();
    int protected_len = packet_len;

    if (api == NULL || session == NULL || fd < 0 || port <= 0) {
        return 0;
    }
    if (api->srtp_protect(session, packet, &protected_len) != 0) {
        return 0;
    }
    send_udp_loopback(fd, port, packet, (size_t)protected_len);
    return 1;
}

static int protect_and_send_srtcp(c300x_srtp_t session, int fd, int port, unsigned char *packet, int packet_len) {
    c300x_srtp_api_t *api = srtp_api();
    int protected_len = packet_len;

    if (api == NULL || session == NULL || fd < 0 || port <= 0) {
        return 0;
    }
    if (api->srtp_protect_rtcp(session, packet, &protected_len) != 0) {
        return 0;
    }
    send_udp_loopback(fd, port, packet, (size_t)protected_len);
    return 1;
}

static void send_media_audio_silence_payload_type(
    int fd,
    int port,
    media_srtp_state_t *state,
    unsigned char payload_type
) {
    unsigned char packet[64];

    if (state == NULL || !state->available) {
        return;
    }
    memset(packet, 0, sizeof(packet));
    packet[0] = 0x80;
    packet[1] = payload_type;
    store_be16(packet + 2, state->audio_seq);
    store_be32(packet + 4, state->audio_timestamp);
    store_be32(packet + 8, state->audio_ssrc);
    packet[12] = MEDIA_AUDIO_SILENCE_PAYLOAD;
    if (protect_and_send_srtp(state->audio, fd, port, packet, 13)) {
        state->audio_seq++;
        state->audio_timestamp += MEDIA_AUDIO_TIMESTAMP_STEP;
    }
}

static void send_media_audio_silence(int fd, int port, media_srtp_state_t *state) {
    send_media_audio_silence_payload_type(fd, port, state, MEDIA_AUDIO_PAYLOAD_TYPE);
}

static bool send_queued_talkback_payload_locked(
    media_bridge_t *bridge,
    int fd,
    int port,
    media_srtp_state_t *state,
    unsigned char payload_type,
    long long *last_talkback_ms
) {
    unsigned char payload[RTSP_BACKCHANNEL_TALKBACK_PAYLOAD_MAX];
    unsigned char packet[512];
    size_t payload_len = 0;
    bool marker = false;

    if (
        state == NULL
        || !state->available
        || last_talkback_ms == NULL
        || !pop_talkback_payload_locked(bridge, payload, &payload_len, &marker)
    ) {
        return false;
    }
    if (payload_len + 12 > sizeof(packet) - 32) {
        return true;
    }
    memset(packet, 0, sizeof(packet));
    packet[0] = 0x80;
    packet[1] = (unsigned char)((marker ? 0x80 : 0) | payload_type);
    store_be16(packet + 2, state->audio_seq);
    store_be32(packet + 4, state->audio_timestamp);
    store_be32(packet + 8, state->audio_ssrc);
    memcpy(packet + 12, payload, payload_len);
    if (protect_and_send_srtp(state->audio, fd, port, packet, (int)(12 + payload_len))) {
        state->audio_seq++;
        state->audio_timestamp += MEDIA_AUDIO_TIMESTAMP_STEP;
        *last_talkback_ms = monotonic_ms();
    }
    return true;
}

static void send_srtcp_receiver_report(int fd, int port, c300x_srtp_t session, uint32_t sender_ssrc) {
    unsigned char packet[64];

    packet[0] = 0x80;
    packet[1] = 201;
    packet[2] = 0x00;
    packet[3] = 0x01;
    store_be32(packet + 4, sender_ssrc);
    (void)protect_and_send_srtcp(session, fd, port, packet, 8);
}

static void send_srtcp_pli(int fd, int port, c300x_srtp_t session, uint32_t sender_ssrc, uint32_t media_ssrc) {
    unsigned char packet[64];

    packet[0] = 0x81;
    packet[1] = 206;
    packet[2] = 0x00;
    packet[3] = 0x02;
    store_be32(packet + 4, sender_ssrc);
    store_be32(packet + 8, media_ssrc);
    (void)protect_and_send_srtcp(session, fd, port, packet, 12);
}

static bool forward_ring_talkback_packet(
    media_bridge_t *bridge,
    const unsigned char *packet,
    ssize_t packet_len
) {
    media_srtp_state_t *state;
    unsigned char out[2048];
    size_t csrc_count;
    size_t header_len;
    size_t payload_len;
    bool ring_active;

    if (bridge == NULL || packet == NULL || packet_len <= 0) {
        return false;
    }

    pthread_mutex_lock(&bridge->mutex);
    ring_active = bridge->ring_call_active && !bridge->ring_call_stop;
    if (
        !ring_active
        || !bridge->ring_answered
        || !bridge->ring_audio_active
        || bridge->ring_srtp_state == NULL
    ) {
        pthread_mutex_unlock(&bridge->mutex);
        return ring_active;
    }
    if (packet_len < 12 || (packet[0] & 0xc0) != 0x80 || (packet[0] & 0x10) != 0) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }
    csrc_count = (size_t)(packet[0] & 0x0f);
    header_len = 12 + (csrc_count * 4);
    if ((size_t)packet_len <= header_len) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }
    payload_len = (size_t)packet_len - header_len;
    if (payload_len + 12 > sizeof(out) - 32) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }

    state = (media_srtp_state_t *)bridge->ring_srtp_state;
    memset(out, 0, sizeof(out));
    out[0] = 0x80;
    out[1] = (unsigned char)((packet[1] & 0x80) | RING_AUDIO_PAYLOAD_TYPE);
    store_be16(out + 2, state->audio_seq);
    store_be32(out + 4, state->audio_timestamp);
    store_be32(out + 8, state->audio_ssrc);
    memcpy(out + 12, packet + header_len, payload_len);
    if (protect_and_send_srtp(
        state->audio,
        bridge->ring_audio_rtp_fd,
        bridge->ring_target_audio_port,
        out,
        (int)(12 + payload_len)
    )) {
        state->audio_seq++;
        state->audio_timestamp += MEDIA_AUDIO_TIMESTAMP_STEP;
        bridge->ring_last_talkback_ms = monotonic_ms();
    }
    pthread_mutex_unlock(&bridge->mutex);
    return true;
}

static bool forward_home_call_talkback_packet(
    media_bridge_t *bridge,
    const unsigned char *packet,
    ssize_t packet_len
) {
    media_srtp_state_t *state;
    unsigned char out[2048];
    size_t csrc_count;
    size_t header_len;
    size_t payload_len;
    bool home_call_active;

    if (bridge == NULL || packet == NULL || packet_len <= 0) {
        return false;
    }

    pthread_mutex_lock(&bridge->mutex);
    home_call_active = bridge->home_call_active && !bridge->home_call_stop;
    if (
        !home_call_active
        || !bridge->home_call_answered
        || bridge->home_call_srtp_state == NULL
    ) {
        pthread_mutex_unlock(&bridge->mutex);
        return home_call_active;
    }
    if (packet_len < 12 || (packet[0] & 0xc0) != 0x80 || (packet[0] & 0x10) != 0) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }
    csrc_count = (size_t)(packet[0] & 0x0f);
    header_len = 12 + (csrc_count * 4);
    if ((size_t)packet_len <= header_len) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }
    payload_len = (size_t)packet_len - header_len;
    if (payload_len + 12 > sizeof(out) - 32) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }

    state = (media_srtp_state_t *)bridge->home_call_srtp_state;
    memset(out, 0, sizeof(out));
    out[0] = 0x80;
    out[1] = (unsigned char)((packet[1] & 0x80) | MEDIA_AUDIO_PAYLOAD_TYPE);
    store_be16(out + 2, state->audio_seq);
    store_be32(out + 4, state->audio_timestamp);
    store_be32(out + 8, state->audio_ssrc);
    memcpy(out + 12, packet + header_len, payload_len);
    if (protect_and_send_srtp(
        state->audio,
        bridge->home_call_audio_rtp_fd,
        bridge->home_call_target_audio_port,
        out,
        (int)(12 + payload_len)
    )) {
        state->audio_seq++;
        state->audio_timestamp += MEDIA_AUDIO_TIMESTAMP_STEP;
        bridge->home_call_last_talkback_ms = monotonic_ms();
    }
    pthread_mutex_unlock(&bridge->mutex);
    return true;
}

static bool forward_ondemand_talkback_packet(
    media_bridge_t *bridge,
    const unsigned char *packet,
    ssize_t packet_len
) {
    media_srtp_state_t *state;
    unsigned char out[2048];
    size_t csrc_count;
    size_t header_len;
    size_t payload_len;
    bool ondemand_active;

    if (bridge == NULL || packet == NULL || packet_len <= 0) {
        return false;
    }

    pthread_mutex_lock(&bridge->mutex);
    ondemand_active = (
        (bridge->media_active || bridge->ondemand_media_started)
        && !bridge->ondemand_media_stop
        && !bridge->stop_in_progress
    );
    if (!ondemand_active || bridge->ondemand_srtp_state == NULL) {
        pthread_mutex_unlock(&bridge->mutex);
        return ondemand_active;
    }
    if (packet_len < 12 || (packet[0] & 0xc0) != 0x80 || (packet[0] & 0x10) != 0) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }
    csrc_count = (size_t)(packet[0] & 0x0f);
    header_len = 12 + (csrc_count * 4);
    if ((size_t)packet_len <= header_len) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }
    payload_len = (size_t)packet_len - header_len;
    if (payload_len + 12 > sizeof(out) - 32) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }

    state = (media_srtp_state_t *)bridge->ondemand_srtp_state;
    memset(out, 0, sizeof(out));
    out[0] = 0x80;
    out[1] = (unsigned char)((packet[1] & 0x80) | MEDIA_AUDIO_PAYLOAD_TYPE);
    store_be16(out + 2, state->audio_seq);
    store_be32(out + 4, state->audio_timestamp);
    store_be32(out + 8, state->audio_ssrc);
    memcpy(out + 12, packet + header_len, payload_len);
    if (protect_and_send_srtp(
        state->audio,
        bridge->ondemand_audio_rtp_fd,
        bridge->ondemand_target_audio_port,
        out,
        (int)(12 + payload_len)
    )) {
        state->audio_seq++;
        state->audio_timestamp += MEDIA_AUDIO_TIMESTAMP_STEP;
        bridge->ondemand_last_talkback_ms = monotonic_ms();
    }
    pthread_mutex_unlock(&bridge->mutex);
    return true;
}

static int16_t decode_pcmu_sample(unsigned char value) {
    const int bias = 0x84;
    int magnitude;

    value = (unsigned char)~value;
    magnitude = ((value & 0x0f) << 3) + bias;
    magnitude <<= (value & 0x70) >> 4;
    return (int16_t)((value & 0x80) ? (bias - magnitude) : (magnitude - bias));
}

static int16_t decode_pcma_sample(unsigned char value) {
    int exponent;
    int mantissa;
    int sample;

    value ^= 0x55;
    exponent = (value & 0x70) >> 4;
    mantissa = value & 0x0f;
    sample = mantissa << 4;
    if (exponent == 0) {
        sample += 8;
    } else {
        sample += 0x108;
        sample <<= exponent - 1;
    }
    return (int16_t)((value & 0x80) ? sample : -sample);
}

static unsigned char encode_pcmu_sample(int16_t sample) {
    const int bias = 0x84;
    const int clip = 32635;
    int sign = 0;
    int magnitude = sample;
    int exponent = 7;
    int exponent_mask = 0x4000;
    int mantissa;
    unsigned char value;

    if (magnitude < 0) {
        sign = 0x80;
        magnitude = -magnitude;
    }
    if (magnitude > clip) {
        magnitude = clip;
    }
    magnitude += bias;
    while (exponent > 0 && (magnitude & exponent_mask) == 0) {
        exponent--;
        exponent_mask >>= 1;
    }
    mantissa = (magnitude >> (exponent + 3)) & 0x0f;
    value = (unsigned char)(sign | (exponent << 4) | mantissa);
    return (unsigned char)~value;
}

static bool queue_speex_backchannel_packet(
    media_bridge_t *bridge,
    const unsigned char *packet,
    size_t packet_len,
    size_t header_len
) {
    size_t payload_len;
    bool marker;
    unsigned int generation;

    if (bridge == NULL || packet == NULL || packet_len <= header_len) {
        return true;
    }
    payload_len = packet_len - header_len;
    marker = (packet[1] & 0x80) != 0;
    pthread_mutex_lock(&bridge->mutex);
    generation = bridge->talkback_backchannel_generation;
    (void)queue_talkback_payload_locked(
        bridge,
        packet + header_len,
        payload_len,
        marker,
        generation
    );
    pthread_mutex_unlock(&bridge->mutex);
    return true;
}

static bool forward_pcm_backchannel_packet(
    media_bridge_t *bridge,
    const unsigned char *packet,
    size_t packet_len,
    size_t header_len,
    unsigned char payload_type
) {
    const unsigned char *payload;
    size_t payload_len;
    size_t offset = 0;
    bool marker_pending;
    uint16_t sequence;
    unsigned int generation;

    if (bridge == NULL || packet == NULL || packet_len <= header_len) {
        return true;
    }
    payload = packet + header_len;
    payload_len = packet_len - header_len;
    marker_pending = (packet[1] & 0x80) != 0;
    sequence = load_be16(packet + 2);

    pthread_mutex_lock(&bridge->mutex);
    generation = bridge->talkback_backchannel_generation;
    if (
        !bridge->talkback_pcm_seq_initialized
        || bridge->talkback_pcm_next_seq != sequence
    ) {
        bridge->talkback_pcm_count = 0;
    }
    bridge->talkback_pcm_seq_initialized = true;
    bridge->talkback_pcm_next_seq = (uint16_t)(sequence + 1);
    pthread_mutex_unlock(&bridge->mutex);

    while (offset < payload_len) {
        int16_t samples[RTSP_BACKCHANNEL_FRAME_SAMPLES];
        unsigned char speex_payload[256];
        size_t speex_len = 0;
        size_t take;
        bool have_frame = false;
        bool frame_marker = false;

        pthread_mutex_lock(&bridge->mutex);
        if (bridge->talkback_backchannel_generation != generation) {
            pthread_mutex_unlock(&bridge->mutex);
            break;
        }
        take = RTSP_BACKCHANNEL_FRAME_SAMPLES - bridge->talkback_pcm_count;
        if (take > payload_len - offset) {
            take = payload_len - offset;
        }
        for (size_t index = 0; index < take; index++) {
            unsigned char sample = payload[offset + index];
            bridge->talkback_pcm_buffer[bridge->talkback_pcm_count + index] =
                payload_type == RTSP_BACKCHANNEL_PCMA_PAYLOAD_TYPE
                    ? decode_pcma_sample(sample)
                    : decode_pcmu_sample(sample);
        }
        bridge->talkback_pcm_count += take;
        offset += take;
        if (bridge->talkback_pcm_count == RTSP_BACKCHANNEL_FRAME_SAMPLES) {
            memcpy(samples, bridge->talkback_pcm_buffer, sizeof(samples));
            bridge->talkback_pcm_count = 0;
            have_frame = true;
            frame_marker = marker_pending;
            marker_pending = false;
        }
        pthread_mutex_unlock(&bridge->mutex);

        if (!have_frame) {
            continue;
        }
        if (!speex_encode_pcm_frame(
            samples,
            speex_payload,
            sizeof(speex_payload),
            &speex_len
        )) {
            continue;
        }
        pthread_mutex_lock(&bridge->mutex);
        (void)queue_talkback_payload_locked(
            bridge,
            speex_payload,
            speex_len,
            frame_marker,
            generation
        );
        pthread_mutex_unlock(&bridge->mutex);
    }
    return true;
}

static bool forward_rtsp_backchannel_packet(
    media_bridge_t *bridge,
    const unsigned char *packet,
    size_t packet_len
) {
    size_t header_len;
    unsigned char payload_type;

    if (bridge == NULL || packet == NULL || packet_len < 12) {
        return false;
    }
    if (!rtp_payload_offset(packet, (int)packet_len, &header_len)) {
        return true;
    }
    if (packet_len <= header_len) {
        return true;
    }
    payload_type = packet[1] & 0x7f;
    if (
        payload_type == C300X_TALKBACK_RTP_PAYLOAD_TYPE
        || payload_type == RING_AUDIO_PAYLOAD_TYPE
        || payload_type == MEDIA_AUDIO_PAYLOAD_TYPE
    ) {
        return queue_speex_backchannel_packet(bridge, packet, packet_len, header_len);
    }
    if (
        payload_type == RTSP_BACKCHANNEL_PCMA_PAYLOAD_TYPE
        || payload_type == RTSP_BACKCHANNEL_PCMU_PAYLOAD_TYPE
    ) {
        return forward_pcm_backchannel_packet(
            bridge,
            packet,
            packet_len,
            header_len,
            payload_type
        );
    }
    return true;
}

static bool handle_rtsp_backchannel_frame(
    media_bridge_t *bridge,
    int slot_index,
    int channel,
    const unsigned char *packet,
    size_t packet_len
) {
    bool matches_backchannel = false;

    pthread_mutex_lock(&bridge->mutex);
    rtsp_client_slot_t *slot = rtsp_client_slot_locked(bridge, slot_index);
    matches_backchannel = slot != NULL
        && slot->backchannel_enabled
        && slot->transport_tcp
        && channel == slot->backchannel_interleaved_channel;
    pthread_mutex_unlock(&bridge->mutex);

    if (!matches_backchannel) {
        return false;
    }
    (void)forward_rtsp_backchannel_packet(bridge, packet, packet_len);
    return true;
}

static void drain_ondemand_media_socket(
    media_bridge_t *bridge,
    int fd,
    c300x_srtp_t session,
    bool rtcp,
    bool audio,
    uint32_t *video_ssrc
) {
    c300x_srtp_api_t *api = srtp_api();
    unsigned char packet[2048];
    struct sockaddr_in from;
    socklen_t from_len = sizeof(from);
    ssize_t n;

    if (api == NULL || bridge == NULL || fd < 0 || session == NULL) {
        return;
    }
    while ((n = recvfrom(fd, packet, sizeof(packet), MSG_DONTWAIT, (struct sockaddr *)&from, &from_len)) > 0) {
        int packet_len = (int)n;
        bool ok = rtcp
            ? api->srtp_unprotect_rtcp(session, packet, &packet_len) == 0
            : api->srtp_unprotect(session, packet, &packet_len) == 0;
        if (ok && !rtcp) {
            if (audio) {
                (void)forward_rtsp_audio_pcmu_packet(bridge, packet, packet_len);
                from_len = sizeof(from);
                continue;
            }
            if (video_ssrc != NULL && packet_len >= 12 && (packet[0] & 0xc0) == 0x80) {
                *video_ssrc = ((uint32_t)packet[8] << 24)
                    | ((uint32_t)packet[9] << 16)
                    | ((uint32_t)packet[10] << 8)
                    | (uint32_t)packet[11];
            }
        }
        from_len = sizeof(from);
    }
}

static void *ondemand_media_thread(void *arg) {
    media_bridge_t *bridge = arg;
    uint32_t video_ssrc = 0;
    unsigned char audio_key[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char video_key[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char audio_in_key[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char video_in_key[MEDIA_SRTP_MASTER_KEY_LEN];
    media_srtp_state_t srtp;
    long long next_media_keepalive = 0;
    long long next_audio_rtp = 0;
    long long next_rtcp = 0;
    long long next_sip_keepalive = 0;
    long long next_bt_av_renew = monotonic_ms() + ((long long)MEDIA_RENEW_SECONDS * 1000LL);

    memset(&srtp, 0, sizeof(srtp));
    pthread_mutex_lock(&bridge->mutex);
    memcpy(audio_key, bridge->ondemand_audio_srtp_key, sizeof(audio_key));
    memcpy(video_key, bridge->ondemand_video_srtp_key, sizeof(video_key));
    memcpy(audio_in_key, bridge->ondemand_audio_srtp_in_key, sizeof(audio_in_key));
    memcpy(video_in_key, bridge->ondemand_video_srtp_in_key, sizeof(video_in_key));
    pthread_mutex_unlock(&bridge->mutex);
    if (
        !media_srtp_init_state(&srtp, audio_key, video_key)
        || !media_srtp_init_inbound(&srtp, audio_in_key, video_in_key)
    ) {
        secure_zero(audio_key, sizeof(audio_key));
        secure_zero(video_key, sizeof(video_key));
        secure_zero(audio_in_key, sizeof(audio_in_key));
        secure_zero(video_in_key, sizeof(video_in_key));
        media_srtp_deinit_state(&srtp);
        pthread_mutex_lock(&bridge->mutex);
        bridge->ondemand_media_started = false;
        if (bridge->ondemand_audio_rtp_fd >= 0) {
            close(bridge->ondemand_audio_rtp_fd);
            bridge->ondemand_audio_rtp_fd = -1;
        }
        if (bridge->ondemand_audio_rtcp_fd >= 0) {
            close(bridge->ondemand_audio_rtcp_fd);
            bridge->ondemand_audio_rtcp_fd = -1;
        }
        if (bridge->ondemand_video_rtp_fd >= 0) {
            close(bridge->ondemand_video_rtp_fd);
            bridge->ondemand_video_rtp_fd = -1;
        }
        if (bridge->ondemand_video_rtcp_fd >= 0) {
            close(bridge->ondemand_video_rtcp_fd);
            bridge->ondemand_video_rtcp_fd = -1;
        }
        pthread_mutex_unlock(&bridge->mutex);
        return NULL;
    }
    secure_zero(audio_key, sizeof(audio_key));
    secure_zero(video_key, sizeof(video_key));
    secure_zero(audio_in_key, sizeof(audio_in_key));
    secure_zero(video_in_key, sizeof(video_in_key));

    pthread_mutex_lock(&bridge->mutex);
    bridge->ondemand_last_talkback_ms = 0;
    bridge->ondemand_srtp_state = &srtp;
    pthread_mutex_unlock(&bridge->mutex);

    while (true) {
        bool stop;
        int sip_fd;
        int audio_rtp_fd;
        int audio_rtcp_fd;
        int video_rtp_fd;
        int video_rtcp_fd;
        int target_audio_port;
        int target_video_port;

        pthread_mutex_lock(&bridge->mutex);
        stop = bridge->ondemand_media_stop || bridge->sip_stop;
        sip_fd = bridge->sip_fd;
        audio_rtp_fd = bridge->ondemand_audio_rtp_fd;
        audio_rtcp_fd = bridge->ondemand_audio_rtcp_fd;
        video_rtp_fd = bridge->ondemand_video_rtp_fd;
        video_rtcp_fd = bridge->ondemand_video_rtcp_fd;
        target_audio_port = bridge->ondemand_target_audio_port;
        target_video_port = bridge->ondemand_target_video_port;
        pthread_mutex_unlock(&bridge->mutex);

        if (stop) {
            break;
        }

        fd_set readfds;
        FD_ZERO(&readfds);
        int max_fd = -1;
        if (audio_rtp_fd >= 0) {
            FD_SET(audio_rtp_fd, &readfds);
            max_fd = audio_rtp_fd > max_fd ? audio_rtp_fd : max_fd;
        }
        if (audio_rtcp_fd >= 0) {
            FD_SET(audio_rtcp_fd, &readfds);
            max_fd = audio_rtcp_fd > max_fd ? audio_rtcp_fd : max_fd;
        }
        if (video_rtp_fd >= 0) {
            FD_SET(video_rtp_fd, &readfds);
            max_fd = video_rtp_fd > max_fd ? video_rtp_fd : max_fd;
        }
        if (video_rtcp_fd >= 0) {
            FD_SET(video_rtcp_fd, &readfds);
            max_fd = video_rtcp_fd > max_fd ? video_rtcp_fd : max_fd;
        }

        if (max_fd < 0) {
            c300x_video_bridge_set_error(bridge->video, "ondemand_media_no_fds");
            break;
        }

        struct timeval timeout = {0, MEDIA_AUDIO_PACKET_MS * 1000};
        if (select(max_fd + 1, &readfds, NULL, NULL, &timeout) > 0) {
            if (audio_rtp_fd >= 0 && FD_ISSET(audio_rtp_fd, &readfds)) {
                drain_ondemand_media_socket(bridge, audio_rtp_fd, srtp.audio_in, false, true, NULL);
            }
            if (audio_rtcp_fd >= 0 && FD_ISSET(audio_rtcp_fd, &readfds)) {
                drain_ondemand_media_socket(bridge, audio_rtcp_fd, srtp.audio_in, true, true, NULL);
            }
            if (video_rtp_fd >= 0 && FD_ISSET(video_rtp_fd, &readfds)) {
                drain_ondemand_media_socket(bridge, video_rtp_fd, srtp.video_in, false, false, &video_ssrc);
            }
            if (video_rtcp_fd >= 0 && FD_ISSET(video_rtcp_fd, &readfds)) {
                drain_ondemand_media_socket(bridge, video_rtcp_fd, srtp.video_in, true, false, NULL);
            }
        }

        long long now = monotonic_ms();
        if (next_media_keepalive == 0 || now >= next_media_keepalive) {
            send_stun_binding_request(audio_rtp_fd, target_audio_port);
            send_stun_binding_request(audio_rtcp_fd, target_audio_port + 1);
            send_stun_binding_request(video_rtp_fd, target_video_port);
            send_stun_binding_request(video_rtcp_fd, target_video_port + 1);
            next_media_keepalive = now + MEDIA_KEEPALIVE_MS;
        }
        if (next_audio_rtp == 0 || now >= next_audio_rtp) {
            pthread_mutex_lock(&bridge->mutex);
            if (bridge->ondemand_srtp_state == &srtp) {
                if (!send_queued_talkback_payload_locked(
                    bridge,
                    audio_rtp_fd,
                    target_audio_port,
                    &srtp,
                    MEDIA_AUDIO_PAYLOAD_TYPE,
                    &bridge->ondemand_last_talkback_ms
                ) && !ondemand_talkback_recent_locked(bridge, now)) {
                    send_media_audio_silence(audio_rtp_fd, target_audio_port, &srtp);
                }
            }
            pthread_mutex_unlock(&bridge->mutex);
            next_audio_rtp = now + MEDIA_AUDIO_PACKET_MS;
        }
        if (next_rtcp == 0 || now >= next_rtcp) {
            pthread_mutex_lock(&bridge->mutex);
            if (bridge->ondemand_srtp_state == &srtp) {
                send_srtcp_receiver_report(audio_rtcp_fd, target_audio_port + 1, srtp.audio, srtp.audio_ssrc);
            }
            pthread_mutex_unlock(&bridge->mutex);
            send_srtcp_receiver_report(video_rtcp_fd, target_video_port + 1, srtp.video, srtp.rtcp_sender_ssrc);
            if (video_ssrc != 0) {
                send_srtcp_pli(video_rtcp_fd, target_video_port + 1, srtp.video, srtp.rtcp_sender_ssrc, video_ssrc);
            }
            next_rtcp = now + 1000;
        }
        if (next_sip_keepalive == 0 || now >= next_sip_keepalive) {
            if (sip_fd >= 0) {
                (void)send_all(sip_fd, "\r\n\r\n", 4);
            }
            next_sip_keepalive = now + ((long long)MEDIA_SIP_KEEPALIVE_SECONDS * 1000LL);
        }
        if (next_bt_av_renew == 0 || now >= next_bt_av_renew) {
            (void)start_bt_av_media(bridge);
            next_bt_av_renew = now + ((long long)MEDIA_RENEW_SECONDS * 1000LL);
        }
    }

    pthread_mutex_lock(&bridge->mutex);
    if (bridge->ondemand_srtp_state == &srtp) {
        bridge->ondemand_srtp_state = NULL;
        reset_backchannel_talkback_locked(bridge);
    }
    bridge->ondemand_last_talkback_ms = 0;
    if (bridge->ondemand_audio_rtp_fd >= 0) {
        close(bridge->ondemand_audio_rtp_fd);
        bridge->ondemand_audio_rtp_fd = -1;
    }
    if (bridge->ondemand_audio_rtcp_fd >= 0) {
        close(bridge->ondemand_audio_rtcp_fd);
        bridge->ondemand_audio_rtcp_fd = -1;
    }
    if (bridge->ondemand_video_rtp_fd >= 0) {
        close(bridge->ondemand_video_rtp_fd);
        bridge->ondemand_video_rtp_fd = -1;
    }
    if (bridge->ondemand_video_rtcp_fd >= 0) {
        close(bridge->ondemand_video_rtcp_fd);
        bridge->ondemand_video_rtcp_fd = -1;
    }
    bridge->ondemand_media_started = false;
    pthread_mutex_unlock(&bridge->mutex);
    media_srtp_deinit_state(&srtp);
    return NULL;
}

static bool send_sip_setup(media_bridge_t *bridge) {
    char domain[128];
    char domain_hint[128] = "";
    char from_user[128];
    char from_aor[256];
    char to_aor[256];
    char local_ip[64];
    uint16_t local_port;
    const char *transport;
    char instance_uuid[MEDIA_INSTANCE_UUID_LEN];
    int ondemand_audio_rtp_fd = -1;
    int ondemand_audio_rtcp_fd = -1;
    int ondemand_video_rtp_fd = -1;
    int ondemand_video_rtcp_fd = -1;
    int target_audio_port = 7078;
    int target_video_port = 9078;
    unsigned char audio_key_raw[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char video_key_raw[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char answer_audio_key_raw[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char answer_video_key_raw[MEDIA_SRTP_MASTER_KEY_LEN];
    char audio_key[64];
    char video_key[64];
    char audio_crypto_aead128[64];
    char audio_crypto_aead256[96];
    char audio_crypto_aes256[96];
    char video_crypto_aead128[64];
    char video_crypto_aead256[96];
    char video_crypto_aes256[96];

    memset(answer_audio_key_raw, 0, sizeof(answer_audio_key_raw));
    memset(answer_video_key_raw, 0, sizeof(answer_video_key_raw));
    (void)sip_domain_from_config(bridge->config, domain_hint, sizeof(domain_hint));
    if (
        !media_identity_from_flexisip(
            domain_hint,
            domain,
            sizeof(domain),
            from_user,
            sizeof(from_user),
            from_aor,
            sizeof(from_aor),
            to_aor,
            sizeof(to_aor)
        )
    ) {
        return false;
    }
    if (!sip_local_endpoint_from_config(bridge->config, local_ip, sizeof(local_ip), &local_port, &transport)) {
        return false;
    }
    if (strcmp(transport, "TCP") != 0) {
        return false;
    }
    if (srtp_api() == NULL) {
        return false;
    }
    if (!bridge_instance_uuid(bridge, bridge->ondemand_instance_uuid, "ondemand", instance_uuid, sizeof(instance_uuid))) {
        return false;
    }

    ondemand_audio_rtp_fd = bind_udp_loopback_port(MEDIA_AUDIO_RTP_PORT);
    ondemand_audio_rtcp_fd = bind_udp_loopback_port(MEDIA_AUDIO_RTCP_PORT);
    ondemand_video_rtp_fd = bind_udp_loopback_port(MEDIA_VIDEO_RTP_PORT);
    ondemand_video_rtcp_fd = bind_udp_loopback_port(MEDIA_VIDEO_RTCP_PORT);
    if (ondemand_audio_rtp_fd < 0 || ondemand_audio_rtcp_fd < 0 || ondemand_video_rtp_fd < 0 || ondemand_video_rtcp_fd < 0) {
        if (ondemand_audio_rtp_fd >= 0) {
            close(ondemand_audio_rtp_fd);
        }
        if (ondemand_audio_rtcp_fd >= 0) {
            close(ondemand_audio_rtcp_fd);
        }
        if (ondemand_video_rtp_fd >= 0) {
            close(ondemand_video_rtp_fd);
        }
        if (ondemand_video_rtcp_fd >= 0) {
            close(ondemand_video_rtcp_fd);
        }
        return false;
    }

    int fd = connect_sip_socket(bridge->config);
    if (fd < 0) {
        close(ondemand_audio_rtp_fd);
        close(ondemand_audio_rtcp_fd);
        close(ondemand_video_rtp_fd);
        close(ondemand_video_rtcp_fd);
        return false;
    }

    long unique_id = (long)time(NULL) ^ (long)getpid();
    char call_id[128];
    char from_tag[64];
    snprintf(call_id, sizeof(call_id), "haapp%ld", unique_id);
    snprintf(from_tag, sizeof(from_tag), "haapp%ld", unique_id);
    if (
        !generate_sdes_key(audio_key_raw, sizeof(audio_key_raw), audio_key, sizeof(audio_key))
        || !generate_sdes_key(video_key_raw, sizeof(video_key_raw), video_key, sizeof(video_key))
        || !generate_random_sdes_key(28, audio_crypto_aead128, sizeof(audio_crypto_aead128))
        || !generate_random_sdes_key(44, audio_crypto_aead256, sizeof(audio_crypto_aead256))
        || !generate_random_sdes_key(46, audio_crypto_aes256, sizeof(audio_crypto_aes256))
        || !generate_random_sdes_key(28, video_crypto_aead128, sizeof(video_crypto_aead128))
        || !generate_random_sdes_key(44, video_crypto_aead256, sizeof(video_crypto_aead256))
        || !generate_random_sdes_key(46, video_crypto_aes256, sizeof(video_crypto_aes256))
    ) {
        secure_zero(audio_key_raw, sizeof(audio_key_raw));
        secure_zero(video_key_raw, sizeof(video_key_raw));
        close(fd);
        close(ondemand_audio_rtp_fd);
        close(ondemand_audio_rtcp_fd);
        close(ondemand_video_rtp_fd);
        close(ondemand_video_rtcp_fd);
        return false;
    }

    char request[8192];
    char response[SIP_BUFFER_SIZE];
    snprintf(
        request,
        sizeof(request),
        "REGISTER sip:%s SIP/2.0\r\n"
        "Via: SIP/2.0/%s %s:%u;branch=z9hG4bKreg%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: <sip:%s>\r\n"
        "From: <sip:%s>;tag=%s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: 20 REGISTER\r\n"
        "Supported: replaces, outbound, gruu\r\n"
        "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE, SUBSCRIBE, INFO, UPDATE\r\n"
        "Contact: <sip:%s;transport=%s>;expires=300;+sip.instance=\"<urn:uuid:%s>\"\r\n"
        "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
        "Expires: 300\r\n"
        "Content-Length: 0\r\n\r\n",
        domain,
        transport,
        local_ip,
        local_port,
        unique_id,
        from_aor,
        from_aor,
        from_tag,
        call_id,
        from_aor,
        transport,
        instance_uuid
    );
    if (send_all(fd, request, strlen(request)) <= 0 || read_message(fd, response, sizeof(response), 3) < 0) {
        secure_zero(audio_key_raw, sizeof(audio_key_raw));
        secure_zero(video_key_raw, sizeof(video_key_raw));
        close(fd);
        close(ondemand_audio_rtp_fd);
        close(ondemand_audio_rtcp_fd);
        close(ondemand_video_rtp_fd);
        close(ondemand_video_rtcp_fd);
        return false;
    }
    if (sip_status_code(response) >= 300) {
        secure_zero(audio_key_raw, sizeof(audio_key_raw));
        secure_zero(video_key_raw, sizeof(video_key_raw));
        close(fd);
        close(ondemand_audio_rtp_fd);
        close(ondemand_audio_rtcp_fd);
        close(ondemand_video_rtp_fd);
        close(ondemand_video_rtcp_fd);
        return false;
    }

    char sdp[4096];
    snprintf(
        sdp,
        sizeof(sdp),
        "v=0\r\n"
        "o=%s 1 1 IN IP4 %s\r\n"
        "s=Talk\r\n"
        "c=IN IP4 %s\r\n"
        "b=AS:380\r\n"
        "t=0 0\r\n"
        "a=rtcp-xr:rcvr-rtt=all:10000 stat-summary=loss,dup,jitt,TTL voip-metrics\r\n"
        "a=DEVADDR:%d\r\n"
        "a=nortpproxy:yes\r\n"
        "m=audio %d RTP/SAVP 96 97 98 0 8 101 99 100\r\n"
        "a=rtpmap:96 opus/48000/2\r\n"
        "a=fmtp:96 useinbandfec=1\r\n"
        "a=rtpmap:97 speex/16000\r\n"
        "a=fmtp:97 vbr=on\r\n"
        "a=rtpmap:98 speex/8000\r\n"
        "a=fmtp:98 vbr=on\r\n"
        "a=rtpmap:101 telephone-event/48000\r\n"
        "a=rtpmap:99 telephone-event/16000\r\n"
        "a=rtpmap:100 telephone-event/8000\r\n"
        "a=crypto:1 AEAD_AES_128_GCM inline:%s\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:%s\r\n"
        "a=crypto:3 AEAD_AES_256_GCM inline:%s\r\n"
        "a=crypto:4 AES_256_CM_HMAC_SHA1_80 inline:%s\r\n"
        "a=rtcp-fb:* trr-int 1000\r\n"
        "a=rtcp-fb:* ccm tmmbr\r\n"
        "m=video %d RTP/SAVP 96 97 98 99\r\n"
        "a=rtpmap:96 AV1/90000\r\n"
        "a=rtpmap:97 VP8/90000\r\n"
        "a=rtpmap:98 H264/90000\r\n"
        "a=fmtp:98 profile-level-id=42801F\r\n"
        "a=rtpmap:99 H265/90000\r\n"
        "a=recvonly\r\n",
        from_user,
        local_ip,
        local_ip,
        doorbell_devaddr(bridge->config),
        MEDIA_AUDIO_RTP_PORT,
        audio_crypto_aead128,
        audio_key,
        audio_crypto_aead256,
        audio_crypto_aes256,
        MEDIA_VIDEO_RTP_PORT
    );
    size_t sdp_used = strlen(sdp);
    (void)c300x_appendf(
        sdp,
        sizeof(sdp),
        &sdp_used,
        "a=crypto:1 AEAD_AES_128_GCM inline:%s\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:%s\r\n"
        "a=crypto:3 AEAD_AES_256_GCM inline:%s\r\n"
        "a=crypto:4 AES_256_CM_HMAC_SHA1_80 inline:%s\r\n"
        "a=rtcp-fb:* trr-int 1000\r\n"
        "a=rtcp-fb:* ccm tmmbr\r\n"
        "a=rtcp-fb:97 nack pli\r\n"
        "a=rtcp-fb:97 nack sli\r\n"
        "a=rtcp-fb:97 ack rpsi\r\n"
        "a=rtcp-fb:97 ccm fir\r\n"
        "a=rtcp-fb:98 nack pli\r\n"
        "a=rtcp-fb:98 ccm fir\r\n"
        "a=rtcp-fb:99 nack pli\r\n"
        "a=rtcp-fb:99 ccm fir\r\n",
        video_crypto_aead128,
        video_key,
        video_crypto_aead256,
        video_crypto_aes256
    );

    snprintf(
        request,
        sizeof(request),
        "INVITE sip:%s SIP/2.0\r\n"
        "Via: SIP/2.0/%s %s:%u;branch=z9hG4bKinv%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: <sip:%s>\r\n"
        "From: <sip:%s>;tag=%s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: 21 INVITE\r\n"
        "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
        "Supported: replaces, outbound, gruu\r\n"
        "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE, SUBSCRIBE, INFO, PRACK, UPDATE\r\n"
        "Contact: <sip:%s;transport=%s>\r\n"
        "Content-Type: application/sdp\r\n"
        "Content-Length: %zu\r\n\r\n%s",
        to_aor,
        transport,
        local_ip,
        local_port,
        unique_id,
        to_aor,
        from_aor,
        from_tag,
        call_id,
        from_aor,
        transport,
        strlen(sdp),
        sdp
    );
    if (send_all(fd, request, strlen(request)) <= 0) {
        secure_zero(audio_key_raw, sizeof(audio_key_raw));
        secure_zero(video_key_raw, sizeof(video_key_raw));
        close(fd);
        close(ondemand_audio_rtp_fd);
        close(ondemand_audio_rtcp_fd);
        close(ondemand_video_rtp_fd);
        close(ondemand_video_rtcp_fd);
        return false;
    }

    int status = 0;
    for (int i = 0; i < 8; i++) {
        if (read_message(fd, response, sizeof(response), 5) < 0) {
            break;
        }
        status = sip_status_code(response);
        if (status >= 200) {
            break;
        }
    }
    if (status < 200 || status >= 300) {
        secure_zero(audio_key_raw, sizeof(audio_key_raw));
        secure_zero(video_key_raw, sizeof(video_key_raw));
        secure_zero(answer_audio_key_raw, sizeof(answer_audio_key_raw));
        secure_zero(answer_video_key_raw, sizeof(answer_video_key_raw));
        close(fd);
        close(ondemand_audio_rtp_fd);
        close(ondemand_audio_rtcp_fd);
        close(ondemand_video_rtp_fd);
        close(ondemand_video_rtcp_fd);
        return false;
    }
    target_audio_port = parse_sdp_media_port(response, "\r\nm=audio ", target_audio_port);
    target_video_port = parse_sdp_media_port(response, "\r\nm=video ", target_video_port);
    if (
        !parse_sdp_sdes_key(response, "\r\nm=audio ", answer_audio_key_raw, sizeof(answer_audio_key_raw))
        || !parse_sdp_sdes_key(response, "\r\nm=video ", answer_video_key_raw, sizeof(answer_video_key_raw))
    ) {
        secure_zero(audio_key_raw, sizeof(audio_key_raw));
        secure_zero(video_key_raw, sizeof(video_key_raw));
        secure_zero(answer_audio_key_raw, sizeof(answer_audio_key_raw));
        secure_zero(answer_video_key_raw, sizeof(answer_video_key_raw));
        close(fd);
        close(ondemand_audio_rtp_fd);
        close(ondemand_audio_rtcp_fd);
        close(ondemand_video_rtp_fd);
        close(ondemand_video_rtcp_fd);
        return false;
    }

    char to_header[512];
    char contact_header[512];
    char contact_uri[512];
    header_value(response, "To:", to_header, sizeof(to_header));
    if (to_header[0] == '\0') {
        snprintf(to_header, sizeof(to_header), "<sip:%s>", to_aor);
    }
    header_value(response, "Contact:", contact_header, sizeof(contact_header));
    sip_uri_from_header(contact_header, contact_uri, sizeof(contact_uri));
    if (contact_uri[0] == '\0') {
        snprintf(contact_uri, sizeof(contact_uri), "sip:%s", to_aor);
    }

    send_sip_ack(fd, from_aor, to_aor, local_ip, local_port, transport, to_header, from_tag, call_id, contact_uri, 21);

    pthread_mutex_lock(&bridge->mutex);
    bridge->sip_fd = fd;
    bridge->sip_stop = false;
    bridge->ondemand_media_stop = false;
    bridge->ondemand_audio_rtp_fd = ondemand_audio_rtp_fd;
    bridge->ondemand_audio_rtcp_fd = ondemand_audio_rtcp_fd;
    bridge->ondemand_video_rtp_fd = ondemand_video_rtp_fd;
    bridge->ondemand_video_rtcp_fd = ondemand_video_rtcp_fd;
    bridge->ondemand_target_audio_port = target_audio_port;
    bridge->ondemand_target_video_port = target_video_port;
    bridge->ondemand_last_talkback_ms = 0;
    bridge->ondemand_srtp_state = NULL;
    memcpy(bridge->ondemand_audio_srtp_key, audio_key_raw, sizeof(bridge->ondemand_audio_srtp_key));
    memcpy(bridge->ondemand_video_srtp_key, video_key_raw, sizeof(bridge->ondemand_video_srtp_key));
    memcpy(bridge->ondemand_audio_srtp_in_key, answer_audio_key_raw, sizeof(bridge->ondemand_audio_srtp_in_key));
    memcpy(bridge->ondemand_video_srtp_in_key, answer_video_key_raw, sizeof(bridge->ondemand_video_srtp_in_key));
    snprintf(bridge->domain, sizeof(bridge->domain), "%s", domain);
    snprintf(bridge->from_aor, sizeof(bridge->from_aor), "%s", from_aor);
    snprintf(bridge->to_aor, sizeof(bridge->to_aor), "%s", to_aor);
    snprintf(bridge->sip_local_ip, sizeof(bridge->sip_local_ip), "%s", local_ip);
    snprintf(bridge->sip_transport, sizeof(bridge->sip_transport), "%s", transport);
    bridge->sip_local_port = local_port;
    snprintf(bridge->call_id, sizeof(bridge->call_id), "%s", call_id);
    snprintf(bridge->from_tag, sizeof(bridge->from_tag), "%s", from_tag);
    snprintf(bridge->to_header, sizeof(bridge->to_header), "%s", to_header);
    snprintf(bridge->contact_uri, sizeof(bridge->contact_uri), "%s", contact_uri);
    bridge->invite_cseq = 21;
    bridge->sip_monitor_started = pthread_create(&bridge->sip_thread, NULL, sip_monitor_thread, bridge) == 0;
    bridge->ondemand_media_started = pthread_create(&bridge->ondemand_media_thread, NULL, ondemand_media_thread, bridge) == 0;
    bool monitor_started = bridge->sip_monitor_started;
    bool ondemand_media_started = bridge->ondemand_media_started;
    pthread_mutex_unlock(&bridge->mutex);
    secure_zero(audio_key_raw, sizeof(audio_key_raw));
    secure_zero(video_key_raw, sizeof(video_key_raw));
    secure_zero(answer_audio_key_raw, sizeof(answer_audio_key_raw));
    secure_zero(answer_video_key_raw, sizeof(answer_video_key_raw));
    return monitor_started && ondemand_media_started;
}

static bool send_bt_av_media_command(const char *command, char *reply, size_t reply_len) {
    int fd = connect_local_tcp(BT_AV_MEDIA_PORT);
    if (fd < 0) {
        return false;
    }
    bool ok = false;
    if (send_all(fd, command, strlen(command)) > 0) {
        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(fd, &readfds);
        struct timeval timeout = {2, 0};
        if (select(fd + 1, &readfds, NULL, NULL, &timeout) > 0) {
            ssize_t n = recv(fd, reply, reply_len - 1, 0);
            if (n > 0) {
                reply[n] = '\0';
                ok = strstr(reply, "*#*1##") != NULL;
            }
        }
    }
    close(fd);
    return ok;
}

static bool start_bt_av_media(media_bridge_t *bridge) {
    char command[128];
    char reply[128] = {0};
    int quality = bridge->config->video_av_high_resolution ? 0 : 1;
    snprintf(
        command,
        sizeof(command),
        "*7*300#127#0#0#1#%d#%d*##",
        video_rtp_port(bridge->config),
        quality
    );
    if (!send_bt_av_media_command(command, reply, sizeof(reply))) {
        return false;
    }

    struct timespec audio_delay = {0, 300000000L};
    (void)nanosleep(&audio_delay, NULL);
    snprintf(
        command,
        sizeof(command),
        "*7*300#127#0#0#1#%d#2*##",
        audio_rtp_port(bridge->config)
    );
    (void)send_bt_av_media_command(command, reply, sizeof(reply));
    return true;
}

static void send_bt_av_media_stop(void) {
    char reply[128] = {0};
    (void)send_bt_av_media_command("*7*0*##", reply, sizeof(reply));
}

static void send_sip_bye(
    int fd,
    const char *from_aor,
    const char *to_aor,
    const char *local_ip,
    uint16_t local_port,
    const char *transport,
    const char *to_header,
    const char *from_tag,
    const char *call_id,
    const char *contact_uri
) {
    if (
        fd < 0
        || from_aor[0] == '\0'
        || to_aor[0] == '\0'
        || local_ip[0] == '\0'
        || transport[0] == '\0'
        || to_header[0] == '\0'
        || from_tag[0] == '\0'
        || call_id[0] == '\0'
    ) {
        return;
    }
    char fallback_uri[512];
    const char *request_uri = contact_uri != NULL && contact_uri[0] != '\0' ? contact_uri : fallback_uri;
    if (contact_uri == NULL || contact_uri[0] == '\0') {
        if (snprintf(fallback_uri, sizeof(fallback_uri), "sip:%s", to_aor) >= (int)sizeof(fallback_uri)) {
            return;
        }
    }
    char request[1024];
    snprintf(
        request,
        sizeof(request),
        "BYE %s SIP/2.0\r\n"
        "Via: SIP/2.0/%s %s:%u;branch=z9hG4bKbye%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: %s\r\n"
        "From: <sip:%s>;tag=%s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: 22 BYE\r\n"
        "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
        "Content-Length: 0\r\n\r\n",
        request_uri,
        transport,
        local_ip,
        local_port,
        (long)time(NULL),
        to_header,
        from_aor,
        from_tag,
        call_id
    );
    (void)send_all(fd, request, strlen(request));
}

static void close_home_call_fds_locked(media_bridge_t *bridge) {
    close_fd_if_open(&bridge->home_call_audio_rtp_fd);
    close_fd_if_open(&bridge->home_call_audio_rtcp_fd);
    close_fd_if_open(&bridge->home_call_sip_fd);
}

static void home_call_cleanup(media_bridge_t *bridge, int fd, int audio_fd, int audio_rtcp_fd) {
    pthread_mutex_lock(&bridge->mutex);
    if (bridge->home_call_sip_fd == fd) {
        bridge->home_call_sip_fd = -1;
    }
    if (bridge->home_call_audio_rtp_fd == audio_fd) {
        bridge->home_call_audio_rtp_fd = -1;
    }
    if (bridge->home_call_audio_rtcp_fd == audio_rtcp_fd) {
        bridge->home_call_audio_rtcp_fd = -1;
    }
    bridge->home_call_started = false;
    bridge->home_call_active = false;
    bridge->home_call_answered = false;
    bridge->home_call_stop = false;
    bridge->home_call_send_bye = false;
    bridge->home_call_rtp_proxy = false;
    bridge->home_call_target_audio_port = 0;
    bridge->home_call_duration_seconds = 0;
    bridge->home_call_last_talkback_ms = 0;
    bridge->home_call_srtp_state = NULL;
    pthread_mutex_unlock(&bridge->mutex);

    if (audio_fd >= 0) {
        close(audio_fd);
    }
    if (audio_rtcp_fd >= 0) {
        close(audio_rtcp_fd);
    }
    if (fd >= 0) {
        shutdown(fd, SHUT_RDWR);
        close(fd);
    }
}

static void drain_home_call_srtp_socket(
    media_bridge_t *bridge,
    int fd,
    c300x_srtp_t session,
    bool rtcp
) {
    c300x_srtp_api_t *api = srtp_api();
    unsigned char packet[2048];
    struct sockaddr_in from;
    socklen_t from_len = sizeof(from);
    ssize_t n;

    if (api == NULL || fd < 0 || session == NULL) {
        return;
    }
    while ((n = recvfrom(fd, packet, sizeof(packet), MSG_DONTWAIT, (struct sockaddr *)&from, &from_len)) > 0) {
        int packet_len = (int)n;
        bool ok = rtcp
            ? api->srtp_unprotect_rtcp(session, packet, &packet_len) == 0
            : api->srtp_unprotect(session, packet, &packet_len) == 0;
        if (ok) {
            pthread_mutex_lock(&bridge->mutex);
            if (rtcp) {
                bridge->home_call_rtcp_packets++;
            } else {
                bridge->home_call_rtp_packets++;
            }
            pthread_mutex_unlock(&bridge->mutex);
            if (!rtcp) {
                (void)forward_rtsp_audio_pcmu_packet(bridge, packet, packet_len);
            }
        }
        from_len = sizeof(from);
    }
}

static void dispatch_home_call_state_event(media_bridge_t *bridge, const char *event_type) {
    struct c300x_video *video;
    bool running;
    bool active;
    bool answered;
    bool rtp_proxy;
    int target_audio_port;
    unsigned long long rtp_packets;
    unsigned long long rtcp_packets;
    char data[384];

    pthread_mutex_lock(&bridge->mutex);
    video = bridge->video;
    running = bridge->home_call_started;
    active = bridge->home_call_active;
    answered = bridge->home_call_answered;
    rtp_proxy = bridge->home_call_rtp_proxy;
    target_audio_port = bridge->home_call_target_audio_port;
    rtp_packets = bridge->home_call_rtp_packets;
    rtcp_packets = bridge->home_call_rtcp_packets;
    pthread_mutex_unlock(&bridge->mutex);

    snprintf(
        data,
        sizeof(data),
        "{\"home_call\":{\"running\":%s,\"active\":%s,\"answered\":%s,"
        "\"rtp_proxy\":%s,\"target_audio_port\":%d,\"rtp_packets\":%llu,"
        "\"rtcp_packets\":%llu}}",
        running ? "true" : "false",
        active ? "true" : "false",
        answered ? "true" : "false",
        rtp_proxy ? "true" : "false",
        target_audio_port,
        rtp_packets,
        rtcp_packets
    );
    c300x_video_dispatch_event(video, event_type, data, 30);
}

static void dispatch_home_call_ended_event(media_bridge_t *bridge) {
    struct c300x_video *video;
    unsigned long long rtp_packets;
    unsigned long long rtcp_packets;
    char data[384];

    pthread_mutex_lock(&bridge->mutex);
    video = bridge->video;
    rtp_packets = bridge->home_call_rtp_packets;
    rtcp_packets = bridge->home_call_rtcp_packets;
    pthread_mutex_unlock(&bridge->mutex);

    snprintf(
        data,
        sizeof(data),
        "{\"home_call\":{\"running\":false,\"active\":false,\"answered\":false,"
        "\"rtp_proxy\":false,\"target_audio_port\":0,\"rtp_packets\":%llu,"
        "\"rtcp_packets\":%llu}}",
        rtp_packets,
        rtcp_packets
    );
    c300x_video_dispatch_event(video, "home_call.ended", data, 30);
}

static bool build_home_call_sdp(
    char *out,
    size_t out_len,
    const char *from_user,
    const char *local_ip,
    const char *crypto_aes_cm
) {
    char crypto_aead128[64];
    char crypto_aead256[96];
    char crypto_aes256[96];
    int session_id = (int)(time(NULL) % 10000);

    if (
        !generate_random_sdes_key(28, crypto_aead128, sizeof(crypto_aead128))
        || !generate_random_sdes_key(44, crypto_aead256, sizeof(crypto_aead256))
        || !generate_random_sdes_key(46, crypto_aes256, sizeof(crypto_aes256))
    ) {
        return false;
    }
    return snprintf(
        out,
        out_len,
        "v=0\r\n"
        "o=%s %d 2019 IN IP4 %s\r\n"
        "s=Talk\r\n"
        "c=IN IP4 %s\r\n"
        "b=AS:380\r\n"
        "t=0 0\r\n"
        "a=rtcp-xr:rcvr-rtt=all:10000 stat-summary=loss,dup,jitt,TTL voip-metrics\r\n"
        "a=nortpproxy:yes\r\n"
        "m=audio %d RTP/SAVP 96 97 98 0 8 101 99 100\r\n"
        "a=rtpmap:96 opus/48000/2\r\n"
        "a=fmtp:96 useinbandfec=1\r\n"
        "a=rtpmap:97 speex/16000\r\n"
        "a=fmtp:97 vbr=on\r\n"
        "a=rtpmap:98 speex/8000\r\n"
        "a=fmtp:98 vbr=on\r\n"
        "a=rtpmap:101 telephone-event/48000\r\n"
        "a=rtpmap:99 telephone-event/16000\r\n"
        "a=rtpmap:100 telephone-event/8000\r\n"
        "a=crypto:1 AEAD_AES_128_GCM inline:%s\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:%s\r\n"
        "a=crypto:3 AEAD_AES_256_GCM inline:%s\r\n"
        "a=crypto:4 AES_256_CM_HMAC_SHA1_80 inline:%s\r\n"
        "a=rtcp-fb:* trr-int 1000\r\n"
        "a=rtcp-fb:* ccm tmmbr\r\n",
        from_user,
        session_id,
        local_ip,
        local_ip,
        HOME_CALL_AUDIO_RTP_PORT,
        crypto_aead128,
        crypto_aes_cm,
        crypto_aead256,
        crypto_aes256
    ) < (int)out_len;
}

static bool send_home_call_register(
    media_bridge_t *bridge,
    int fd,
    const char *domain,
    const char *from_aor,
    const char *local_ip,
    uint16_t local_port,
    int cseq
) {
    char request[2048];
    char response[SIP_BUFFER_SIZE];
    char instance_uuid[MEDIA_INSTANCE_UUID_LEN];
    long unique_id = (long)time(NULL) ^ (long)getpid() ^ (long)cseq;
    if (!bridge_instance_uuid(bridge, bridge->home_call_instance_uuid, "home_call", instance_uuid, sizeof(instance_uuid))) {
        return false;
    }
    int len = snprintf(
        request,
        sizeof(request),
        "REGISTER sip:%s SIP/2.0\r\n"
        "Via: SIP/2.0/TCP %s:%u;branch=z9hG4bKhomecallreg%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: <sip:%s>\r\n"
        "From: <sip:%s>;tag=ha-homecall%ld\r\n"
        "Call-ID: ha-home-call-register-%ld\r\n"
        "CSeq: %d REGISTER\r\n"
        "Supported: replaces, outbound, gruu\r\n"
        "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE, SUBSCRIBE, INFO, UPDATE\r\n"
        "Contact: <sip:%s;transport=tcp>;expires=300;+sip.instance=\"<urn:uuid:%s>\"\r\n"
        "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
        "Expires: 300\r\n"
        "Content-Length: 0\r\n\r\n",
        domain,
        local_ip,
        local_port,
        unique_id,
        from_aor,
        from_aor,
        unique_id,
        unique_id,
        cseq,
        from_aor,
        instance_uuid
    );
    if (len <= 0 || len >= (int)sizeof(request)) {
        return false;
    }
    if (send_all(fd, request, (size_t)len) <= 0) {
        return false;
    }
    if (read_message(fd, response, sizeof(response), 3) < 0) {
        return false;
    }
    return sip_status_code(response) >= 200 && sip_status_code(response) < 300;
}

static bool send_home_call_invite(
    media_bridge_t *bridge,
    int fd,
    const char *to_aor,
    const char *from_aor,
    const char *from_tag,
    const char *call_id,
    const char *invite_branch,
    const char *local_ip,
    uint16_t local_port,
    const char *sdp
) {
    char request[8192];
    char instance_uuid[MEDIA_INSTANCE_UUID_LEN];
    if (!bridge_instance_uuid(bridge, bridge->home_call_instance_uuid, "home_call", instance_uuid, sizeof(instance_uuid))) {
        return false;
    }
    int len = snprintf(
        request,
        sizeof(request),
        "INVITE sip:%s SIP/2.0\r\n"
        "Via: SIP/2.0/TCP %s:%u;branch=%s;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: <sip:%s>\r\n"
        "From: <sip:%s>;tag=%s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: 21 INVITE\r\n"
        "Contact: <sip:%s;gr=urn:uuid:%s>;+sip.instance=\"<urn:uuid:%s>\"\r\n"
        "User-Agent: " MEDIA_SIP_USER_AGENT "\r\n"
        "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE, SUBSCRIBE, INFO, PRACK, UPDATE\r\n"
        "Supported: replaces, outbound, gruu\r\n"
        "Content-Type: application/sdp\r\n"
        "Content-Length: %zu\r\n\r\n%s",
        to_aor,
        local_ip,
        local_port,
        invite_branch,
        to_aor,
        from_aor,
        from_tag,
        call_id,
        from_aor,
        instance_uuid,
        instance_uuid,
        strlen(sdp),
        sdp
    );
    if (len <= 0 || len >= (int)sizeof(request)) {
        return false;
    }
    return send_all(fd, request, (size_t)len) == len;
}

static void send_home_call_cancel(
    int fd,
    const char *to_aor,
    const char *from_aor,
    const char *from_tag,
    const char *call_id,
    const char *invite_branch,
    const char *local_ip,
    uint16_t local_port,
    const char *transport
) {
    char request[2048];
    int len;

    if (
        fd < 0
        || to_aor[0] == '\0'
        || from_aor[0] == '\0'
        || from_tag[0] == '\0'
        || call_id[0] == '\0'
        || invite_branch[0] == '\0'
        || local_ip[0] == '\0'
        || transport[0] == '\0'
    ) {
        return;
    }
    len = snprintf(
        request,
        sizeof(request),
        "CANCEL sip:%s SIP/2.0\r\n"
        "Via: SIP/2.0/%s %s:%u;branch=%s;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: <sip:%s>\r\n"
        "From: <sip:%s>;tag=%s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: 21 CANCEL\r\n"
        "Content-Length: 0\r\n\r\n",
        to_aor,
        transport,
        local_ip,
        local_port,
        invite_branch,
        to_aor,
        from_aor,
        from_tag,
        call_id
    );
    if (len > 0 && len < (int)sizeof(request)) {
        (void)send_all(fd, request, (size_t)len);
    }
}

static void drain_home_call_stop_responses(
    int fd,
    const char *stop_method,
    bool wait_invite_final
) {
    char message[SIP_BUFFER_SIZE];
    bool stop_response_seen = false;
    bool invite_final_seen = !wait_invite_final;
    long long deadline = monotonic_ms() + 2000;

    if (fd < 0 || stop_method == NULL || stop_method[0] == '\0') {
        return;
    }
    while (monotonic_ms() < deadline) {
        int n = read_message_poll(fd, message, sizeof(message), 1);
        if (n <= 0) {
            continue;
        }
        if (strncmp(message, "\r\n\r\n", 4) == 0) {
            continue;
        }
        if (strncmp(message, "OPTIONS ", 8) == 0 || strncmp(message, "NOTIFY ", 7) == 0) {
            send_sip_ok_response(fd, message);
            continue;
        }
        if (strncmp(message, "BYE ", 4) == 0 || strncmp(message, "CANCEL ", 7) == 0) {
            send_sip_ok_response(fd, message);
            continue;
        }

        int status = sip_status_code(message);
        if (status >= 200) {
            char cseq_method[16];
            cseq_method_value(message, cseq_method, sizeof(cseq_method));
            if (strcmp(cseq_method, stop_method) == 0) {
                stop_response_seen = true;
            }
            if (wait_invite_final && strcmp(cseq_method, "INVITE") == 0) {
                invite_final_seen = true;
            }
            if (stop_response_seen && invite_final_seen) {
                return;
            }
        }
    }
}

static void *home_call_thread_func(void *arg) {
    media_bridge_t *bridge = arg;
    char domain[128];
    char domain_hint[128] = "";
    char from_user[128];
    char from_aor[256];
    char to_aor[256];
    char local_ip[64];
    uint16_t local_port;
    const char *transport;
    int fd = -1;
    int audio_fd = -1;
    int audio_rtcp_fd = -1;
    int duration_seconds;
    unsigned char offer_audio_key_raw[MEDIA_SRTP_MASTER_KEY_LEN];
    unsigned char answer_audio_key_raw[MEDIA_SRTP_MASTER_KEY_LEN];
    char offer_audio_key[64];
    char sdp[4096];
    char message[SIP_BUFFER_SIZE];
    char call_id[128];
    char from_tag[64];
    char invite_branch[64];
    char to_header[512];
    char contact_header[512];
    char contact_uri[512];
    int target_audio_port = 7078;
    media_srtp_state_t srtp;
    bool srtp_ready = false;
    bool invite_sent = false;
    bool answered = false;
    bool started_event_sent = false;
    bool answered_event_sent = false;
    bool dispatch_ended = false;
    long long ring_deadline = monotonic_ms() + ((long long)HOME_CALL_DEFAULT_RING_TIMEOUT_SECONDS * 1000LL);
    long long call_deadline = 0;
    long long next_audio = 0;
    long long next_rtcp = 0;
    long long next_stun = 0;
    long long next_sip_keepalive = 0;

    memset(&srtp, 0, sizeof(srtp));
    memset(offer_audio_key_raw, 0, sizeof(offer_audio_key_raw));
    memset(answer_audio_key_raw, 0, sizeof(answer_audio_key_raw));
    to_header[0] = '\0';
    contact_uri[0] = '\0';

    pthread_mutex_lock(&bridge->mutex);
    duration_seconds = bridge->home_call_duration_seconds;
    pthread_mutex_unlock(&bridge->mutex);

    (void)sip_domain_from_config(bridge->config, domain_hint, sizeof(domain_hint));
    if (
        !media_identity_from_flexisip(
            domain_hint,
            domain,
            sizeof(domain),
            from_user,
            sizeof(from_user),
            from_aor,
            sizeof(from_aor),
            to_aor,
            sizeof(to_aor)
        )
        || !sip_local_endpoint_from_config(bridge->config, local_ip, sizeof(local_ip), &local_port, &transport)
        || strcmp(transport, "TCP") != 0
        || srtp_api() == NULL
    ) {
        c300x_video_bridge_set_error(bridge->video, "home_call_identity_failed");
        goto cleanup;
    }

    audio_fd = bind_udp_loopback_port(HOME_CALL_AUDIO_RTP_PORT);
    audio_rtcp_fd = bind_udp_loopback_port(HOME_CALL_AUDIO_RTCP_PORT);
    if (audio_fd < 0 || audio_rtcp_fd < 0) {
        c300x_video_bridge_set_error(bridge->video, "home_call_audio_socket_failed");
        goto cleanup;
    }
    if (
        !generate_sdes_key(offer_audio_key_raw, sizeof(offer_audio_key_raw), offer_audio_key, sizeof(offer_audio_key))
        || !build_home_call_sdp(sdp, sizeof(sdp), from_user, local_ip, offer_audio_key)
    ) {
        c300x_video_bridge_set_error(bridge->video, "home_call_sdp_failed");
        goto cleanup;
    }
    if (!media_srtp_init_audio_state(&srtp, offer_audio_key_raw)) {
        c300x_video_bridge_set_error(bridge->video, "home_call_srtp_failed");
        goto cleanup;
    }
    srtp_ready = true;

    fd = connect_sip_socket(bridge->config);
    if (fd < 0) {
        c300x_video_bridge_set_error(bridge->video, "home_call_sip_connect_failed");
        goto cleanup;
    }
    if (!send_home_call_register(bridge, fd, domain, from_aor, local_ip, local_port, 20)) {
        c300x_video_bridge_set_error(bridge->video, "home_call_register_failed");
        goto cleanup;
    }

    long unique_id = (long)time(NULL) ^ (long)getpid();
    snprintf(call_id, sizeof(call_id), "hahomecall%ld", unique_id);
    snprintf(from_tag, sizeof(from_tag), "hahomecall%ld", unique_id);
    snprintf(invite_branch, sizeof(invite_branch), "z9hG4bKhomecallinv%ld", unique_id);
    if (!send_home_call_invite(bridge, fd, to_aor, from_aor, from_tag, call_id, invite_branch, local_ip, local_port, sdp)) {
        c300x_video_bridge_set_error(bridge->video, "home_call_invite_failed");
        goto cleanup;
    }
    invite_sent = true;
    pthread_mutex_lock(&bridge->mutex);
    bridge->home_call_sip_fd = fd;
    bridge->home_call_audio_rtp_fd = audio_fd;
    bridge->home_call_audio_rtcp_fd = audio_rtcp_fd;
    bridge->home_call_active = true;
    bridge->home_call_answered = false;
    bridge->home_call_rtp_proxy = false;
    bridge->home_call_target_audio_port = 0;
    bridge->home_call_rtp_packets = 0;
    bridge->home_call_rtcp_packets = 0;
    bridge->home_call_last_talkback_ms = 0;
    reset_backchannel_talkback_locked(bridge);
    bridge->home_call_srtp_state = NULL;
    pthread_mutex_unlock(&bridge->mutex);
    dispatch_home_call_state_event(bridge, "home_call.started");
    started_event_sent = true;

    while (!answered && monotonic_ms() < ring_deadline) {
        bool stop;
        bool send_bye;

        pthread_mutex_lock(&bridge->mutex);
        stop = bridge->home_call_stop;
        send_bye = bridge->home_call_send_bye;
        pthread_mutex_unlock(&bridge->mutex);
        if (stop) {
            if (send_bye && invite_sent) {
                send_home_call_cancel(fd, to_aor, from_aor, from_tag, call_id, invite_branch, local_ip, local_port, transport);
                drain_home_call_stop_responses(fd, "CANCEL", true);
            }
            goto cleanup;
        }

        int n = read_message_poll(fd, message, sizeof(message), 1);
        if (n < 0) {
            c300x_video_bridge_set_error(bridge->video, "home_call_sip_read_failed");
            goto cleanup;
        }
        if (n == 0 || strncmp(message, "\r\n\r\n", 4) == 0) {
            continue;
        }
        if (strncmp(message, "OPTIONS ", 8) == 0 || strncmp(message, "NOTIFY ", 7) == 0) {
            send_sip_ok_response(fd, message);
            continue;
        }
        if (strncmp(message, "BYE ", 4) == 0 || strncmp(message, "CANCEL ", 7) == 0) {
            send_sip_ok_response(fd, message);
            goto cleanup;
        }
        int status = sip_status_code(message);
        if (status == 0 || status < 200) {
            continue;
        }
        if (status >= 300) {
            c300x_video_bridge_set_error(bridge->video, "home_call_rejected");
            goto cleanup;
        }
        target_audio_port = parse_sdp_media_port(message, "\r\nm=audio ", 7078);
        header_value(message, "To:", to_header, sizeof(to_header));
        if (to_header[0] == '\0') {
            snprintf(to_header, sizeof(to_header), "<sip:%s>", to_aor);
        }
        header_value(message, "Contact:", contact_header, sizeof(contact_header));
        sip_uri_from_header(contact_header, contact_uri, sizeof(contact_uri));
        if (contact_uri[0] == '\0') {
            snprintf(contact_uri, sizeof(contact_uri), "sip:%s", to_aor);
        }
        if (
            !parse_sdp_sdes_key(message, "\r\nm=audio ", answer_audio_key_raw, sizeof(answer_audio_key_raw))
            || !media_srtp_init_audio_inbound(&srtp, answer_audio_key_raw)
        ) {
            c300x_video_bridge_set_error(bridge->video, "home_call_answer_srtp_failed");
            goto cleanup;
        }
        send_sip_ack(fd, from_aor, to_aor, local_ip, local_port, transport, to_header, from_tag, call_id, contact_uri, 21);
        pthread_mutex_lock(&bridge->mutex);
        bridge->home_call_answered = true;
        bridge->home_call_target_audio_port = target_audio_port;
        bridge->home_call_rtp_proxy = target_audio_port != 7078;
        bridge->home_call_last_talkback_ms = 0;
        bridge->home_call_srtp_state = &srtp;
        pthread_mutex_unlock(&bridge->mutex);
        if (!start_talkback_proxy(bridge)) {
            c300x_video_bridge_set_error(bridge->video, "home_call_talkback_start_failed");
        }
        dispatch_home_call_state_event(bridge, "home_call.answered");
        answered_event_sent = true;
        answered = true;
        if (duration_seconds > 0) {
            call_deadline = monotonic_ms() + ((long long)duration_seconds * 1000LL);
        }
    }

    if (!answered) {
        if (invite_sent) {
            send_home_call_cancel(fd, to_aor, from_aor, from_tag, call_id, invite_branch, local_ip, local_port, transport);
        }
        c300x_video_bridge_set_error(bridge->video, "home_call_answer_timeout");
        goto cleanup;
    }

    while (true) {
        bool stop;
        bool send_bye;

        pthread_mutex_lock(&bridge->mutex);
        stop = bridge->home_call_stop;
        send_bye = bridge->home_call_send_bye;
        pthread_mutex_unlock(&bridge->mutex);
        if ((call_deadline > 0 && monotonic_ms() >= call_deadline) || stop) {
            if (send_bye || call_deadline > 0) {
                send_sip_bye(fd, from_aor, to_aor, local_ip, local_port, transport, to_header, from_tag, call_id, contact_uri);
                drain_home_call_stop_responses(fd, "BYE", false);
            }
            break;
        }

        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(fd, &readfds);
        int max_fd = fd;
        FD_SET(audio_fd, &readfds);
        max_fd = audio_fd > max_fd ? audio_fd : max_fd;
        FD_SET(audio_rtcp_fd, &readfds);
        max_fd = audio_rtcp_fd > max_fd ? audio_rtcp_fd : max_fd;
        struct timeval timeout = {0, MEDIA_AUDIO_PACKET_MS * 1000};
        int ready = select(max_fd + 1, &readfds, NULL, NULL, &timeout);
        if (ready > 0) {
            if (FD_ISSET(fd, &readfds)) {
                int n = read_message(fd, message, sizeof(message), 1);
                if (n < 0) {
                    break;
                }
                if (n > 0 && strncmp(message, "\r\n\r\n", 4) != 0) {
                    if (strncmp(message, "BYE ", 4) == 0 || strncmp(message, "CANCEL ", 7) == 0) {
                        send_sip_ok_response(fd, message);
                        break;
                    }
                    if (strncmp(message, "OPTIONS ", 8) == 0 || strncmp(message, "NOTIFY ", 7) == 0) {
                        send_sip_ok_response(fd, message);
                    }
                }
            }
            if (FD_ISSET(audio_fd, &readfds)) {
                drain_home_call_srtp_socket(bridge, audio_fd, srtp.audio_in, false);
            }
            if (FD_ISSET(audio_rtcp_fd, &readfds)) {
                drain_home_call_srtp_socket(bridge, audio_rtcp_fd, srtp.audio_in, true);
            }
        }

        long long now = monotonic_ms();
        if (next_stun == 0 || now >= next_stun) {
            send_stun_binding_request(audio_fd, target_audio_port);
            send_stun_binding_request(audio_rtcp_fd, target_audio_port + 1);
            next_stun = now + MEDIA_KEEPALIVE_MS;
        }
        if (next_audio == 0 || now >= next_audio) {
            pthread_mutex_lock(&bridge->mutex);
            if (bridge->home_call_srtp_state == &srtp) {
                if (!send_queued_talkback_payload_locked(
                    bridge,
                    audio_fd,
                    target_audio_port,
                    &srtp,
                    MEDIA_AUDIO_PAYLOAD_TYPE,
                    &bridge->home_call_last_talkback_ms
                ) && !home_call_talkback_recent_locked(bridge, now)) {
                    send_media_audio_silence(audio_fd, target_audio_port, &srtp);
                }
            }
            pthread_mutex_unlock(&bridge->mutex);
            next_audio = now + MEDIA_AUDIO_PACKET_MS;
        }
        if (next_rtcp == 0 || now >= next_rtcp) {
            send_srtcp_receiver_report(audio_rtcp_fd, target_audio_port + 1, srtp.audio, srtp.audio_ssrc);
            next_rtcp = now + 1000;
        }
        if (next_sip_keepalive == 0 || now >= next_sip_keepalive) {
            (void)send_all(fd, "\r\n\r\n", 4);
            next_sip_keepalive = now + ((long long)MEDIA_SIP_KEEPALIVE_SECONDS * 1000LL);
        }
    }

cleanup:
    dispatch_ended = started_event_sent || answered_event_sent || invite_sent;
    pthread_mutex_lock(&bridge->mutex);
    if (bridge->home_call_srtp_state == &srtp) {
        bridge->home_call_srtp_state = NULL;
        reset_backchannel_talkback_locked(bridge);
    }
    bridge->home_call_last_talkback_ms = 0;
    pthread_mutex_unlock(&bridge->mutex);
    if (srtp_ready) {
        media_srtp_deinit_state(&srtp);
    }
    secure_zero(offer_audio_key_raw, sizeof(offer_audio_key_raw));
    secure_zero(answer_audio_key_raw, sizeof(answer_audio_key_raw));
    home_call_cleanup(bridge, fd, audio_fd, audio_rtcp_fd);
    if (dispatch_ended) {
        dispatch_home_call_ended_event(bridge);
    }
    return NULL;
}

static void *rtp_relay_thread(void *arg) {
    media_bridge_t *bridge = arg;
    unsigned char packet[2048];

    while (true) {
        pthread_mutex_lock(&bridge->mutex);
        bool stop = bridge->relay_stop;
        int rtp_fd = bridge->rtp_fd;
        int audio_rtp_fd = bridge->audio_rtp_fd;
        pthread_mutex_unlock(&bridge->mutex);

        if (stop || rtp_fd < 0) {
            break;
        }

        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(rtp_fd, &readfds);
        int max_fd = rtp_fd;
        if (audio_rtp_fd >= 0) {
            FD_SET(audio_rtp_fd, &readfds);
            if (audio_rtp_fd > max_fd) {
                max_fd = audio_rtp_fd;
            }
        }
        struct timeval timeout = {0, 200000};
        int ready = select(max_fd + 1, &readfds, NULL, NULL, &timeout);
        if (ready <= 0) {
            continue;
        }

        if (audio_rtp_fd >= 0 && FD_ISSET(audio_rtp_fd, &readfds)) {
            ssize_t n = recv(audio_rtp_fd, packet, sizeof(packet), 0);
            if (n > 0) {
                (void)forward_rtsp_audio_pcmu_packet(bridge, packet, (int)n);
            }
        }
        if (!FD_ISSET(rtp_fd, &readfds)) {
            continue;
        }

        ssize_t n = recv(rtp_fd, packet, sizeof(packet), 0);
        if (n <= 0) {
            continue;
        }
        forward_rtsp_packet(bridge, packet, (int)n, false);
    }

    pthread_mutex_lock(&bridge->mutex);
    if (bridge->rtp_fd >= 0) {
        close(bridge->rtp_fd);
        bridge->rtp_fd = -1;
    }
    if (bridge->audio_rtp_fd >= 0) {
        close(bridge->audio_rtp_fd);
        bridge->audio_rtp_fd = -1;
    }
    bridge->media_active = false;
    pthread_mutex_unlock(&bridge->mutex);
    return NULL;
}

static int bind_udp_port(int port) {
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
        return -1;
    }
    int opt = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static int bind_udp_loopback_port(int port) {
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
        return -1;
    }
    int opt = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr) != 1) {
        close(fd);
        return -1;
    }
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static void *talkback_proxy_thread(void *arg) {
    media_bridge_t *bridge = arg;
    unsigned char packet[2048];
    int listen_fd = bind_udp_port(C300X_TALKBACK_RTP_PORT);
    int target_fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (listen_fd < 0 || target_fd < 0) {
        if (listen_fd >= 0) {
            close(listen_fd);
        }
        if (target_fd >= 0) {
            close(target_fd);
        }
        pthread_mutex_lock(&bridge->mutex);
        bridge->talkback_started = false;
        bridge->talkback_fd = -1;
        pthread_mutex_unlock(&bridge->mutex);
        return NULL;
    }

    struct sockaddr_in target;
    memset(&target, 0, sizeof(target));
    target.sin_family = AF_INET;
    target.sin_port = htons((uint16_t)TALKBACK_TARGET_PORT);
    (void)inet_pton(AF_INET, "127.0.0.1", &target.sin_addr);

    pthread_mutex_lock(&bridge->mutex);
    bridge->talkback_fd = listen_fd;
    pthread_mutex_unlock(&bridge->mutex);

    while (true) {
        pthread_mutex_lock(&bridge->mutex);
        bool stop = bridge->talkback_stop;
        pthread_mutex_unlock(&bridge->mutex);
        if (stop) {
            break;
        }

        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(listen_fd, &readfds);
        struct timeval timeout = {0, 200000};
        int ready = select(listen_fd + 1, &readfds, NULL, NULL, &timeout);
        if (ready <= 0) {
            continue;
        }

        ssize_t n = recv(listen_fd, packet, sizeof(packet), 0);
        if (n > 0) {
            if (
                !forward_ring_talkback_packet(bridge, packet, n)
                && !forward_home_call_talkback_packet(bridge, packet, n)
                && !forward_ondemand_talkback_packet(bridge, packet, n)
            ) {
                (void)sendto(target_fd, packet, (size_t)n, 0, (struct sockaddr *)&target, sizeof(target));
            }
        }
    }

    close(listen_fd);
    close(target_fd);
    pthread_mutex_lock(&bridge->mutex);
    bridge->talkback_fd = -1;
    bridge->talkback_started = false;
    pthread_mutex_unlock(&bridge->mutex);
    return NULL;
}

static bool start_talkback_proxy(media_bridge_t *bridge) {
    pthread_mutex_lock(&bridge->mutex);
    if (bridge->talkback_started) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }
    bridge->talkback_stop = false;
    bridge->talkback_started = pthread_create(&bridge->talkback_thread, NULL, talkback_proxy_thread, bridge) == 0;
    bool started = bridge->talkback_started;
    pthread_mutex_unlock(&bridge->mutex);
    return started;
}

static bool create_rtp_socket(media_bridge_t *bridge) {
    int video_fd = bind_udp_port(video_rtp_port(bridge->config));
    if (video_fd < 0) {
        return false;
    }
    int audio_fd = bind_udp_port(audio_rtp_port(bridge->config));
    if (audio_fd < 0) {
        close(video_fd);
        return false;
    }
    bridge->rtp_fd = video_fd;
    bridge->audio_rtp_fd = audio_fd;
    return true;
}

static bool start_media_session(media_bridge_t *bridge) __attribute__((noinline));
static void stop_media_session(bool close_client);

static bool start_media_session(media_bridge_t *bridge) {
    pthread_mutex_lock(&bridge->mutex);
    if (bridge->stop_in_progress) {
        pthread_mutex_unlock(&bridge->mutex);
        return false;
    }
    if (bridge->media_active || bridge->media_starting) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }
    reset_backchannel_talkback_locked(bridge);
    bridge->media_starting = true;
    bridge->relay_stop = false;
    if (!create_rtp_socket(bridge)) {
        bridge->media_starting = false;
        pthread_mutex_unlock(&bridge->mutex);
        c300x_video_bridge_set_error(bridge->video, "rtp_socket_failed");
        c300x_video_bridge_media_stopped(bridge->video);
        return false;
    }
    pthread_mutex_unlock(&bridge->mutex);
    c300x_video_bridge_media_starting(bridge->video);

    if (!send_sip_setup(bridge)) {
        c300x_video_bridge_set_error(bridge->video, "ondemand_sip_setup_failed");
        stop_media_session(false);
        c300x_video_bridge_media_stopped(bridge->video);
        return false;
    }
    if (!start_talkback_proxy(bridge)) {
        c300x_video_bridge_set_error(bridge->video, "talkback_start_failed");
        stop_media_session(false);
        c300x_video_bridge_media_stopped(bridge->video);
        return false;
    }
    if (!start_bt_av_media(bridge)) {
        c300x_video_bridge_set_error(bridge->video, "bt_av_media_start_failed");
        stop_media_session(false);
        c300x_video_bridge_media_stopped(bridge->video);
        return false;
    }

    pthread_mutex_lock(&bridge->mutex);
    bridge->media_active = true;
    bridge->media_starting = false;
    bridge->relay_started = pthread_create(&bridge->relay_thread, NULL, rtp_relay_thread, bridge) == 0;
    bool started = bridge->relay_started;
    pthread_mutex_unlock(&bridge->mutex);

    if (!started) {
        c300x_video_bridge_set_error(bridge->video, "rtp_relay_start_failed");
        stop_media_session(false);
        c300x_video_bridge_media_stopped(bridge->video);
        return false;
    }
    c300x_video_bridge_media_started(bridge->video, true);
    c300x_video_dispatch_event(bridge->video, "doorbell.view_requested", "{}", 0);
    return true;
}

static void stop_media_session(bool close_client) {
    int sip_fd = -1;
    char from_aor[256];
    char to_aor[256];
    char local_ip[64];
    char transport[4];
    uint16_t local_port = DEFAULT_SIP_PORT;
    char call_id[128];
    char from_tag[64];
    char to_header[512];
    char contact_uri[512];
    bool relay_started = false;
    bool sip_monitor_started = false;
    bool ondemand_media_started = false;
    bool talkback_started = false;
    bool send_media_stop = false;
    pthread_t sip_thread;
    pthread_t ondemand_media_thread_id;
    pthread_t talkback_thread;

    from_aor[0] = '\0';
    to_aor[0] = '\0';
    local_ip[0] = '\0';
    transport[0] = '\0';
    call_id[0] = '\0';
    from_tag[0] = '\0';
    to_header[0] = '\0';
    contact_uri[0] = '\0';

    pthread_mutex_lock(&g_bridge.mutex);
    if (g_bridge.stop_in_progress) {
        if (close_client) {
            shutdown_all_rtsp_clients_locked(&g_bridge);
        }
        pthread_mutex_unlock(&g_bridge.mutex);
        return;
    }
    if (
        !g_bridge.media_active
        && !g_bridge.media_starting
        && !g_bridge.relay_started
        && !g_bridge.sip_monitor_started
        && !g_bridge.ondemand_media_started
        && !g_bridge.talkback_started
        && g_bridge.rtp_fd < 0
        && g_bridge.audio_rtp_fd < 0
        && g_bridge.ondemand_audio_rtp_fd < 0
        && g_bridge.ondemand_audio_rtcp_fd < 0
        && g_bridge.ondemand_video_rtp_fd < 0
        && g_bridge.ondemand_video_rtcp_fd < 0
        && g_bridge.sip_fd < 0
        && g_bridge.talkback_fd < 0
    ) {
        if (close_client) {
            shutdown_all_rtsp_clients_locked(&g_bridge);
        }
        pthread_mutex_unlock(&g_bridge.mutex);
        return;
    }
    g_bridge.stop_in_progress = true;
    g_bridge.relay_stop = true;
    g_bridge.sip_stop = true;
    g_bridge.ondemand_media_stop = true;
    g_bridge.talkback_stop = true;
    send_media_stop = g_bridge.media_active || g_bridge.relay_started;
    relay_started = g_bridge.relay_started;
    sip_monitor_started = g_bridge.sip_monitor_started;
    ondemand_media_started = g_bridge.ondemand_media_started;
    talkback_started = g_bridge.talkback_started;
    sip_thread = g_bridge.sip_thread;
    ondemand_media_thread_id = g_bridge.ondemand_media_thread;
    talkback_thread = g_bridge.talkback_thread;
    g_bridge.relay_started = false;
    g_bridge.talkback_started = false;
    sip_fd = g_bridge.sip_fd;
    snprintf(from_aor, sizeof(from_aor), "%s", g_bridge.from_aor);
    snprintf(to_aor, sizeof(to_aor), "%s", g_bridge.to_aor);
    snprintf(local_ip, sizeof(local_ip), "%s", g_bridge.sip_local_ip);
    snprintf(transport, sizeof(transport), "%s", g_bridge.sip_transport);
    local_port = g_bridge.sip_local_port;
    snprintf(call_id, sizeof(call_id), "%s", g_bridge.call_id);
    snprintf(from_tag, sizeof(from_tag), "%s", g_bridge.from_tag);
    snprintf(to_header, sizeof(to_header), "%s", g_bridge.to_header);
    snprintf(contact_uri, sizeof(contact_uri), "%s", g_bridge.contact_uri);
    g_bridge.sip_fd = -1;
    if (close_client) {
        shutdown_all_rtsp_clients_locked(&g_bridge);
    }
    pthread_mutex_unlock(&g_bridge.mutex);

    if (sip_fd >= 0) {
        send_sip_bye(sip_fd, from_aor, to_aor, local_ip, local_port, transport, to_header, from_tag, call_id, contact_uri);
        shutdown(sip_fd, SHUT_RDWR);
    }
    if (sip_monitor_started && !pthread_equal(sip_thread, pthread_self())) {
        pthread_join(sip_thread, NULL);
    }

    if (relay_started) {
        pthread_join(g_bridge.relay_thread, NULL);
    }
    if (talkback_started) {
        pthread_join(talkback_thread, NULL);
    }
    if (ondemand_media_started && !pthread_equal(ondemand_media_thread_id, pthread_self())) {
        pthread_join(ondemand_media_thread_id, NULL);
    }

    if (sip_fd >= 0) {
        close(sip_fd);
    }
    if (send_media_stop) {
        send_bt_av_media_stop();
    }

    pthread_mutex_lock(&g_bridge.mutex);
    g_bridge.media_active = false;
    g_bridge.media_starting = false;
    g_bridge.sip_stop = false;
    g_bridge.ondemand_media_stop = false;
    g_bridge.talkback_stop = false;
    g_bridge.sip_monitor_started = false;
    g_bridge.ondemand_media_started = false;
    if (g_bridge.rtp_fd >= 0) {
        close(g_bridge.rtp_fd);
        g_bridge.rtp_fd = -1;
    }
    if (g_bridge.audio_rtp_fd >= 0) {
        close(g_bridge.audio_rtp_fd);
        g_bridge.audio_rtp_fd = -1;
    }
    if (g_bridge.ondemand_audio_rtp_fd >= 0) {
        close(g_bridge.ondemand_audio_rtp_fd);
        g_bridge.ondemand_audio_rtp_fd = -1;
    }
    if (g_bridge.ondemand_audio_rtcp_fd >= 0) {
        close(g_bridge.ondemand_audio_rtcp_fd);
        g_bridge.ondemand_audio_rtcp_fd = -1;
    }
    if (g_bridge.ondemand_video_rtp_fd >= 0) {
        close(g_bridge.ondemand_video_rtp_fd);
        g_bridge.ondemand_video_rtp_fd = -1;
    }
    if (g_bridge.ondemand_video_rtcp_fd >= 0) {
        close(g_bridge.ondemand_video_rtcp_fd);
        g_bridge.ondemand_video_rtcp_fd = -1;
    }
    if (g_bridge.talkback_fd >= 0) {
        close(g_bridge.talkback_fd);
        g_bridge.talkback_fd = -1;
    }
    g_bridge.domain[0] = '\0';
    g_bridge.from_aor[0] = '\0';
    g_bridge.to_aor[0] = '\0';
    g_bridge.sip_local_ip[0] = '\0';
    g_bridge.sip_transport[0] = '\0';
    g_bridge.sip_local_port = 0;
    g_bridge.call_id[0] = '\0';
    g_bridge.from_tag[0] = '\0';
    g_bridge.to_header[0] = '\0';
    g_bridge.contact_uri[0] = '\0';
    g_bridge.ondemand_target_audio_port = 0;
    g_bridge.ondemand_target_video_port = 0;
    g_bridge.ondemand_last_talkback_ms = 0;
    g_bridge.ondemand_srtp_state = NULL;
    reset_backchannel_talkback_locked(&g_bridge);
    memset(g_bridge.ondemand_audio_srtp_key, 0, sizeof(g_bridge.ondemand_audio_srtp_key));
    memset(g_bridge.ondemand_video_srtp_key, 0, sizeof(g_bridge.ondemand_video_srtp_key));
    g_bridge.stop_in_progress = false;
    pthread_mutex_unlock(&g_bridge.mutex);
}

void c300x_media_session_stop(struct c300x_video *video) {
    bool dispatch_closed;
    bool owned;
    bool ring_dispatch_closed;

    pthread_mutex_lock(&g_bridge.mutex);
    owned = g_bridge.video == video;
    ring_dispatch_closed = (
        owned
        && !home_call_active_locked(&g_bridge)
        && !g_bridge.ring_call_stop
        && (g_bridge.ring_call_active || g_bridge.ring_media_active)
    );
    dispatch_closed = owned && doorbell_media_session_active_locked(&g_bridge);
    pthread_mutex_unlock(&g_bridge.mutex);

    if (stop_ring_call_if_active(true, true)) {
        c300x_video_bridge_media_stopped(g_bridge.video);
        if (
            ring_dispatch_closed
            && c300x_video_consume_media_closed_event(video)
        ) {
            c300x_video_dispatch_event(video, "doorbell.media.closed", "{}", 0);
        }
        return;
    }
    stop_media_session(true);
    c300x_video_bridge_media_stopped(g_bridge.video);
    if (dispatch_closed && c300x_video_consume_media_closed_event(video)) {
        c300x_video_dispatch_event(video, "doorbell.media.closed", "{}", 0);
    }
}

bool c300x_media_session_stop_in_progress(const struct c300x_video *video) {
    bool stopping;

    pthread_mutex_lock(&g_bridge.mutex);
    stopping = g_bridge.video == video && g_bridge.stop_in_progress;
    pthread_mutex_unlock(&g_bridge.mutex);
    return stopping;
}

bool c300x_media_session_keepalive(struct c300x_video *video, bool audio) {
    bool ready;
    bool active;

    pthread_mutex_lock(&g_bridge.mutex);
    ready = g_bridge.running && g_bridge.config != NULL && g_bridge.video == video;
    active = g_bridge.media_active && !g_bridge.media_starting && !g_bridge.stop_in_progress;
    pthread_mutex_unlock(&g_bridge.mutex);

    if (!ready || !active) {
        return false;
    }
    c300x_video_bridge_media_started(g_bridge.video, audio);
    return true;
}

bool c300x_media_ring_call_answer(struct c300x_video *video) {
    bool ready;

    pthread_mutex_lock(&g_bridge.mutex);
    ready = g_bridge.video == video && g_bridge.ring_call_active && !g_bridge.ring_call_stop;
    pthread_mutex_unlock(&g_bridge.mutex);
    if (!ready) {
        return false;
    }
    return request_ring_answer_if_active(&g_bridge);
}

void c300x_media_ring_call_hangup(struct c300x_video *video) {
    bool owned;

    pthread_mutex_lock(&g_bridge.mutex);
    owned = g_bridge.video == video;
    pthread_mutex_unlock(&g_bridge.mutex);
    if (!owned) {
        return;
    }
    c300x_media_session_stop(video);
}

bool c300x_media_talkback_running(const struct c300x_video *video) {
    bool running;

    pthread_mutex_lock(&g_bridge.mutex);
    running = g_bridge.running
        && g_bridge.video == video
        && g_bridge.talkback_started
        && !g_bridge.talkback_stop
        && g_bridge.talkback_fd >= 0;
    pthread_mutex_unlock(&g_bridge.mutex);
    return running;
}

void c300x_media_bridge_status(const struct c300x_video *video, struct c300x_video_status *status)
{
    int open_fds = 0;
    int active_threads = 0;

    if (status == NULL) {
        return;
    }
    pthread_mutex_lock(&g_bridge.mutex);
    if (g_bridge.video == video) {
        status->bridge_running = g_bridge.running ? 1 : 0;
        status->bridge_media_active = (
            g_bridge.media_active
            || g_bridge.ring_media_active
            || g_bridge.home_call_active
        ) ? 1 : 0;
        status->bridge_stop_in_progress = g_bridge.stop_in_progress ? 1 : 0;
        status->ring_receiver_running = g_bridge.ring_started ? 1 : 0;
        status->ring_registered = g_bridge.ring_registered ? 1 : 0;
        status->ring_call_active = g_bridge.ring_call_active ? 1 : 0;
        status->ring_media_active = g_bridge.ring_media_active ? 1 : 0;
        status->ring_audio_active = g_bridge.ring_audio_active ? 1 : 0;
        status->ring_answer_requested = g_bridge.ring_answer_requested ? 1 : 0;
        status->ring_answered = g_bridge.ring_answered ? 1 : 0;
        status->home_call_running = g_bridge.home_call_started ? 1 : 0;
        status->home_call_active = g_bridge.home_call_active ? 1 : 0;
        status->home_call_answered = g_bridge.home_call_answered ? 1 : 0;
        status->home_call_rtp_proxy = g_bridge.home_call_rtp_proxy ? 1 : 0;
        status->home_call_target_audio_port = g_bridge.home_call_target_audio_port;
        status->home_call_rtp_packets = g_bridge.home_call_rtp_packets;
        status->home_call_rtcp_packets = g_bridge.home_call_rtcp_packets;
        status->max_clients = rtsp_client_sharing_allowed_locked(&g_bridge)
            ? C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS
            : 1;
        open_fds += g_bridge.listen_fd >= 0 ? 1 : 0;
        open_fds += rtsp_client_count_locked(&g_bridge);
        open_fds += g_bridge.rtp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.audio_rtp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.ondemand_audio_rtp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.ondemand_audio_rtcp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.ondemand_video_rtp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.ondemand_video_rtcp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.talkback_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.sip_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.ring_sip_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.ring_audio_rtp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.ring_audio_rtcp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.ring_video_rtp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.ring_video_rtcp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.home_call_sip_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.home_call_audio_rtp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.home_call_audio_rtcp_fd >= 0 ? 1 : 0;
        active_threads += g_bridge.running ? 1 : 0;
        active_threads += g_bridge.relay_started ? 1 : 0;
        active_threads += g_bridge.sip_monitor_started ? 1 : 0;
        active_threads += g_bridge.ondemand_media_started ? 1 : 0;
        active_threads += g_bridge.talkback_started ? 1 : 0;
        active_threads += g_bridge.ring_started ? 1 : 0;
        active_threads += g_bridge.home_call_started ? 1 : 0;
        active_threads += g_bridge.rtsp_client_threads;
        status->bridge_open_fds = open_fds;
        status->bridge_active_threads = active_threads;
    }
    pthread_mutex_unlock(&g_bridge.mutex);
}

static int parse_client_port(const char *transport) {
    const char *pos = strstr(transport, "client_port=");
    if (pos == NULL) {
        return 0;
    }
    return atoi(pos + 12);
}

static int parse_interleaved_channel(const char *transport) {
    const char *pos = strstr(transport, "interleaved=");
    if (pos == NULL) {
        return -1;
    }
    return atoi(pos + 12);
}

static void send_rtsp_response(
    int fd,
    int status,
    const char *cseq,
    const char *headers,
    const char *body
) __attribute__((noinline));

static void send_rtsp_response(
    int fd,
    int status,
    const char *cseq,
    const char *headers,
    const char *body
) {
    const char *status_text = status == 200 ? "OK" : "Error";
    size_t body_len = body ? strlen(body) : 0;
    char response[4096];
    int n = snprintf(
        response,
        sizeof(response),
        "RTSP/1.0 %d %s\r\n"
        "CSeq: %s\r\n"
        "%s"
        "Content-Length: %zu\r\n"
        "\r\n"
        "%s",
        status,
        status_text,
        cseq && cseq[0] ? cseq : "1",
        headers ? headers : "",
        body_len,
        body ? body : ""
    );
    if (n > 0 && n < (int)sizeof(response)) {
        (void)send_all(fd, response, (size_t)n);
    }
}

static void handle_rtsp_client(int fd, struct sockaddr_storage *peer) {
    char *request = calloc(1, RTSP_BUFFER_SIZE);
    unsigned char interleaved[2048];
    char method[16];
    char uri[512];
    char cseq[64];
    char transport[512];
    char session_id[32];
    bool media_started = false;
    int slot_index = -1;
    int remaining_clients = 0;

    if (request == NULL) {
        close(fd);
        return;
    }

    pthread_mutex_lock(&g_bridge.mutex);
    bool accepted = register_rtsp_client_locked(&g_bridge, fd, &slot_index);
    pthread_mutex_unlock(&g_bridge.mutex);
    if (!accepted) {
        send_rtsp_response(fd, 453, "1", NULL, NULL);
        free(request);
        close(fd);
        return;
    }
    c300x_video_bridge_client_connected(g_bridge.video);

    while (g_bridge.running) {
        int interleaved_channel = -1;
        size_t interleaved_len = 0;
        rtsp_read_result_t read_result = read_rtsp_request_or_interleaved(
            fd,
            request,
            RTSP_BUFFER_SIZE,
            interleaved,
            sizeof(interleaved),
            &interleaved_channel,
            &interleaved_len,
            media_started ? RTSP_IDLE_TIMEOUT_SECONDS : 30
        );
        if (read_result == RTSP_READ_INTERLEAVED) {
            if (interleaved_len > 0) {
                (void)handle_rtsp_backchannel_frame(
                    &g_bridge,
                    slot_index,
                    interleaved_channel,
                    interleaved,
                    interleaved_len
                );
            }
            continue;
        }
        if (read_result != RTSP_READ_REQUEST) {
            break;
        }
        method[0] = '\0';
        uri[0] = '\0';
        cseq[0] = '\0';
        transport[0] = '\0';
        (void)sscanf(request, "%15s %511s", method, uri);
        header_value(request, "CSeq:", cseq, sizeof(cseq));
        header_value(request, "Transport:", transport, sizeof(transport));
        bool recorder = strstr(uri, "/doorbell-recorder") != NULL;
        bool preview_path = strstr(uri, "/doorbell-video") != NULL || recorder;

        if (strcmp(method, "OPTIONS") == 0) {
            send_rtsp_response(fd, 200, cseq, "Public: OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN, GET_PARAMETER\r\n", NULL);
        } else if (strcmp(method, "DESCRIBE") == 0) {
            bool wants_audio = strstr(uri, "/doorbell") != NULL && strstr(uri, "/doorbell-video") == NULL && strstr(uri, "/doorbell-recorder") == NULL;
            pthread_mutex_lock(&g_bridge.mutex);
            bool ring_audio = ring_call_active_locked(&g_bridge);
            bool home_call_audio = home_call_active_locked(&g_bridge);
            bool shared_client = rtsp_client_count_locked(&g_bridge) > 1;
            rtsp_client_slot_t *slot = rtsp_client_slot_locked(&g_bridge, slot_index);
            bool ring_preview_sharing = ring_preview_sharing_allowed_locked(&g_bridge);
            bool ring_answer_stream_sharing = ring_answer_stream_sharing_allowed_locked(&g_bridge);
            bool allow_shared_path = !shared_client
                || (
                    ring_preview_sharing
                    && preview_path
                    && !wants_audio
                )
                || (
                    ring_answer_stream_sharing
                    && wants_audio
                    && !preview_path
                );
            if (slot != NULL && allow_shared_path) {
                slot->audio_enabled = wants_audio;
                slot->recorder = recorder;
                slot->video_interleaved_channel = wants_audio ? 2 : 0;
                slot->audio_interleaved_channel = 0;
                slot->backchannel_enabled = false;
                slot->backchannel_interleaved_channel = -1;
                sync_legacy_rtsp_client_locked(&g_bridge);
            }
            pthread_mutex_unlock(&g_bridge.mutex);
            if (!allow_shared_path) {
                send_rtsp_response(fd, 453, cseq, NULL, NULL);
                break;
            }
            const char *sdp_audio_video =
                "v=0\r\n"
                "o=- 0 0 IN IP4 127.0.0.1\r\n"
                "s=BTicino Doorbell\r\n"
                "c=IN IP4 0.0.0.0\r\n"
                "t=0 0\r\n"
                "m=audio 0 RTP/AVP 0\r\n"
                "a=rtpmap:0 PCMU/8000\r\n"
                "a=control:streamid=0\r\n"
                "m=video 0 RTP/AVP 96\r\n"
                "a=rtpmap:96 H264/90000\r\n"
                "a=fmtp:96 profile-level-id=42801F\r\n"
                "a=rtcp-fb:* trr-int 5000\r\n"
                "a=rtcp-fb:* ccm tmmbr\r\n"
                "a=rtcp-fb:96 nack pli\r\n"
                "a=rtcp-fb:96 ccm fir\r\n"
                "a=control:streamid=1\r\n"
                "m=audio 0 RTP/AVP 8 0\r\n"
                "a=rtpmap:8 PCMA/8000\r\n"
                "a=rtpmap:0 PCMU/8000\r\n"
                "a=control:streamid=2\r\n"
                "a=recvonly\r\n";
            const char *sdp_ring_audio_video =
                "v=0\r\n"
                "o=- 0 0 IN IP4 127.0.0.1\r\n"
                "s=BTicino Doorbell\r\n"
                "c=IN IP4 0.0.0.0\r\n"
                "t=0 0\r\n"
                "m=audio 0 RTP/AVP 0\r\n"
                "a=rtpmap:0 PCMU/8000\r\n"
                "a=control:streamid=0\r\n"
                "m=video 0 RTP/AVP 96\r\n"
                "a=rtpmap:96 H264/90000\r\n"
                "a=fmtp:96 profile-level-id=42801F\r\n"
                "a=rtcp-fb:* trr-int 5000\r\n"
                "a=rtcp-fb:* ccm tmmbr\r\n"
                "a=rtcp-fb:96 nack pli\r\n"
                "a=rtcp-fb:96 ccm fir\r\n"
                "a=control:streamid=1\r\n"
                "m=audio 0 RTP/AVP 8 0\r\n"
                "a=rtpmap:8 PCMA/8000\r\n"
                "a=rtpmap:0 PCMU/8000\r\n"
                "a=control:streamid=2\r\n"
                "a=recvonly\r\n";
            const char *sdp_home_call_audio =
                "v=0\r\n"
                "o=- 0 0 IN IP4 127.0.0.1\r\n"
                "s=BTicino Home Call\r\n"
                "c=IN IP4 0.0.0.0\r\n"
                "t=0 0\r\n"
                "m=audio 0 RTP/AVP 0\r\n"
                "a=rtpmap:0 PCMU/8000\r\n"
                "a=control:streamid=0\r\n"
                "m=audio 0 RTP/AVP 8 0\r\n"
                "a=rtpmap:8 PCMA/8000\r\n"
                "a=rtpmap:0 PCMU/8000\r\n"
                "a=control:streamid=2\r\n"
                "a=recvonly\r\n";
            const char *sdp_video =
                "v=0\r\n"
                "o=- 0 0 IN IP4 127.0.0.1\r\n"
                "s=BTicino Doorbell\r\n"
                "c=IN IP4 0.0.0.0\r\n"
                "t=0 0\r\n"
                "m=video 0 RTP/AVP 96\r\n"
                "a=rtpmap:96 H264/90000\r\n"
                "a=fmtp:96 profile-level-id=42801F\r\n"
                "a=rtcp-fb:* trr-int 5000\r\n"
                "a=rtcp-fb:* ccm tmmbr\r\n"
                "a=rtcp-fb:96 nack pli\r\n"
                "a=rtcp-fb:96 ccm fir\r\n"
                "a=control:streamid=1\r\n";
            const char *sdp = sdp_video;
            if (wants_audio) {
                sdp = home_call_audio
                    ? sdp_home_call_audio
                    : (ring_audio ? sdp_ring_audio_video : sdp_audio_video);
            }
            char headers[512];
            snprintf(headers, sizeof(headers), "Content-Type: application/sdp\r\nContent-Base: %s/\r\n", uri);
            send_rtsp_response(fd, 200, cseq, headers, sdp);
        } else if (strcmp(method, "SETUP") == 0) {
            bool tcp = strstr(transport, "RTP/AVP/TCP") != NULL;
            int client_port = parse_client_port(transport);
            int interleaved_channel = parse_interleaved_channel(transport);
            pthread_mutex_lock(&g_bridge.mutex);
            rtsp_client_slot_t *slot = rtsp_client_slot_locked(&g_bridge, slot_index);
            bool rtsp_audio_enabled = slot != NULL && slot->audio_enabled;
            pthread_mutex_unlock(&g_bridge.mutex);
            bool is_backchannel = rtsp_audio_enabled
                && (
                    strstr(uri, "streamid=2") != NULL
                    || strstr(uri, "backchannel") != NULL
                );
            bool is_audio = rtsp_audio_enabled
                && !is_backchannel
                && strstr(uri, "streamid=0") != NULL;
            int server_port = is_audio ? audio_rtp_port(g_bridge.config) : video_rtp_port(g_bridge.config);
            if (interleaved_channel < 0) {
                interleaved_channel = is_backchannel
                    ? 4
                    : (is_audio ? 0 : (rtsp_audio_enabled ? 2 : 0));
            }
            pthread_mutex_lock(&g_bridge.mutex);
            slot = rtsp_client_slot_locked(&g_bridge, slot_index);
            if (slot == NULL) {
                pthread_mutex_unlock(&g_bridge.mutex);
                break;
            }
            slot->transport_tcp = tcp;
            if (is_backchannel) {
                slot->backchannel_enabled = true;
                slot->backchannel_interleaved_channel = interleaved_channel;
            } else if (is_audio) {
                slot->audio_interleaved_channel = interleaved_channel;
            } else {
                slot->video_interleaved_channel = interleaved_channel;
            }
            memset(&slot->udp_client, 0, sizeof(slot->udp_client));
            if (!tcp && client_port > 0 && rtsp_peer_ipv4_address(peer, &slot->udp_client.sin_addr)) {
                slot->udp_client.sin_family = AF_INET;
                slot->udp_client.sin_port = htons((uint16_t)client_port);
            }
            snprintf(session_id, sizeof(session_id), "%s", slot->session_id);
            sync_legacy_rtsp_client_locked(&g_bridge);
            pthread_mutex_unlock(&g_bridge.mutex);

            char headers[512];
            if (tcp) {
                snprintf(
                    headers,
                    sizeof(headers),
                    "Transport: RTP/AVP/TCP;unicast;interleaved=%d-%d;ssrc=1A2B3C4D\r\nSession: %s;timeout=%d\r\n",
                    interleaved_channel,
                    interleaved_channel + 1,
                    session_id,
                    RTSP_IDLE_TIMEOUT_SECONDS
                );
            } else {
                snprintf(
                    headers,
                    sizeof(headers),
                    "Transport: RTP/AVP;unicast;client_port=%d-%d;server_port=%d-%d;ssrc=1A2B3C4D\r\nSession: %s;timeout=%d\r\n",
                    client_port,
                    client_port + 1,
                    server_port,
                    server_port + 1,
                    session_id,
                    RTSP_IDLE_TIMEOUT_SECONDS
                );
            }
            send_rtsp_response(fd, 200, cseq, headers, NULL);
        } else if (strcmp(method, "PLAY") == 0) {
            bool rtsp_audio_enabled = false;
            bool close_preview_after_play = false;
            pthread_mutex_lock(&g_bridge.mutex);
            rtsp_client_slot_t *slot = rtsp_client_slot_locked(&g_bridge, slot_index);
            if (slot != NULL) {
                rtsp_audio_enabled = slot->audio_enabled;
                snprintf(session_id, sizeof(session_id), "%s", slot->session_id);
            } else {
                session_id[0] = '\0';
            }
            pthread_mutex_unlock(&g_bridge.mutex);
            bool home_call_session = request_home_call_media_if_active(&g_bridge, rtsp_audio_enabled);
            bool ring_session = !home_call_session && ring_session_active(&g_bridge);
            if (recorder && !ring_session && !home_call_session) {
                ring_session = wait_for_ring_session_active(&g_bridge, 1500);
                if (!ring_session) {
                    send_rtsp_response(fd, 503, cseq, NULL, NULL);
                    break;
                }
            }
            if (!ring_session && !home_call_session && !start_media_session(&g_bridge)) {
                send_rtsp_response(fd, 500, cseq, NULL, NULL);
                break;
            }
            media_started = !ring_session && !home_call_session;
            if (ring_session && rtsp_audio_enabled) {
                pthread_mutex_lock(&g_bridge.mutex);
                close_preview_after_play = g_bridge.ring_answered;
                pthread_mutex_unlock(&g_bridge.mutex);
            }
            char headers[256];
            snprintf(
                headers,
                sizeof(headers),
                "Session: %s\r\nRTP-Info: url=%s/streamid=%d;seq=0;rtptime=0\r\n",
                session_id,
                uri,
                home_call_session ? 0 : 1
            );
            send_rtsp_response(fd, 200, cseq, headers, NULL);
            if (close_preview_after_play) {
                pthread_mutex_lock(&g_bridge.mutex);
                shutdown_ring_preview_clients_except_locked(&g_bridge, slot_index);
                pthread_mutex_unlock(&g_bridge.mutex);
            }
        } else if (strcmp(method, "GET_PARAMETER") == 0) {
            char headers[128];
            pthread_mutex_lock(&g_bridge.mutex);
            rtsp_client_slot_t *slot = rtsp_client_slot_locked(&g_bridge, slot_index);
            snprintf(session_id, sizeof(session_id), "%s", slot != NULL ? slot->session_id : "");
            pthread_mutex_unlock(&g_bridge.mutex);
            snprintf(headers, sizeof(headers), "Session: %s\r\n", session_id);
            send_rtsp_response(fd, 200, cseq, headers, NULL);
        } else if (strcmp(method, "TEARDOWN") == 0) {
            char headers[128];
            pthread_mutex_lock(&g_bridge.mutex);
            rtsp_client_slot_t *slot = rtsp_client_slot_locked(&g_bridge, slot_index);
            snprintf(session_id, sizeof(session_id), "%s", slot != NULL ? slot->session_id : "");
            pthread_mutex_unlock(&g_bridge.mutex);
            snprintf(headers, sizeof(headers), "Session: %s\r\n", session_id);
            send_rtsp_response(fd, 200, cseq, headers, NULL);
            break;
        } else {
            send_rtsp_response(fd, 404, cseq, NULL, NULL);
        }
    }

    pthread_mutex_lock(&g_bridge.mutex);
    unregister_rtsp_client_locked(&g_bridge, slot_index);
    remaining_clients = rtsp_client_count_locked(&g_bridge);
    pthread_mutex_unlock(&g_bridge.mutex);
    c300x_video_bridge_client_disconnected(g_bridge.video);

    if (media_started && remaining_clients == 0) {
        c300x_media_session_stop(g_bridge.video);
        c300x_video_bridge_media_stopped(g_bridge.video);
    }
    free(request);
    close(fd);
}

static void *rtsp_client_thread(void *arg) {
    rtsp_client_thread_arg_t *client = arg;

    if (client == NULL) {
        return NULL;
    }
    handle_rtsp_client(client->fd, &client->peer);
    free(client);
    pthread_mutex_lock(&g_bridge.mutex);
    if (g_bridge.rtsp_client_threads > 0) {
        g_bridge.rtsp_client_threads--;
    }
    pthread_cond_broadcast(&g_bridge.ready_cond);
    pthread_mutex_unlock(&g_bridge.mutex);
    return NULL;
}

static int create_rtsp_listener(uint16_t port) {
    int opt = 1;
    int off = 0;
    int server_fd = socket(AF_INET6, SOCK_STREAM, 0);

    if (server_fd >= 0) {
        struct sockaddr_in6 addr6;
        setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
        (void)setsockopt(server_fd, IPPROTO_IPV6, IPV6_V6ONLY, &off, sizeof(off));
        memset(&addr6, 0, sizeof(addr6));
        addr6.sin6_family = AF_INET6;
        addr6.sin6_port = htons(port);
        addr6.sin6_addr = in6addr_any;
        if (bind(server_fd, (struct sockaddr *)&addr6, sizeof(addr6)) == 0 && listen(server_fd, 8) == 0) {
            return server_fd;
        }
        close(server_fd);
    }

    server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd >= 0) {
        struct sockaddr_in addr;
        setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
        memset(&addr, 0, sizeof(addr));
        addr.sin_family = AF_INET;
        addr.sin_port = htons(port);
        addr.sin_addr.s_addr = htonl(INADDR_ANY);
        if (bind(server_fd, (struct sockaddr *)&addr, sizeof(addr)) == 0 && listen(server_fd, 8) == 0) {
            return server_fd;
        }
        close(server_fd);
    }
    return -1;
}

static void *rtsp_server_thread(void *arg) {
    media_bridge_t *bridge = arg;
    int server_fd = create_rtsp_listener(bridge->config->video_rtsp_port);
    if (server_fd < 0) {
        pthread_mutex_lock(&bridge->mutex);
        bridge->startup_done = true;
        bridge->startup_ok = false;
        bridge->running = false;
        pthread_cond_broadcast(&bridge->ready_cond);
        pthread_mutex_unlock(&bridge->mutex);
        return NULL;
    }
    pthread_mutex_lock(&bridge->mutex);
    bridge->listen_fd = server_fd;
    bridge->startup_done = true;
    bridge->startup_ok = true;
    pthread_cond_broadcast(&bridge->ready_cond);
    pthread_mutex_unlock(&bridge->mutex);

    while (bridge->running) {
        struct sockaddr_storage peer;
        socklen_t peer_len = sizeof(peer);
        int client_fd = accept(server_fd, (struct sockaddr *)&peer, &peer_len);
        if (client_fd < 0) {
            if (errno == EINTR) {
                continue;
            }
            break;
        }
        rtsp_client_thread_arg_t *client = calloc(1, sizeof(*client));
        if (client == NULL) {
            close(client_fd);
            continue;
        }
        client->fd = client_fd;
        client->peer = peer;
        pthread_t client_thread;
        pthread_mutex_lock(&bridge->mutex);
        bridge->rtsp_client_threads++;
        pthread_mutex_unlock(&bridge->mutex);
        if (pthread_create(&client_thread, NULL, rtsp_client_thread, client) == 0) {
            pthread_detach(client_thread);
        } else {
            pthread_mutex_lock(&bridge->mutex);
            if (bridge->rtsp_client_threads > 0) {
                bridge->rtsp_client_threads--;
            }
            pthread_cond_broadcast(&bridge->ready_cond);
            pthread_mutex_unlock(&bridge->mutex);
            free(client);
            close(client_fd);
        }
    }

    bool should_close = true;
    pthread_mutex_lock(&bridge->mutex);
    if (bridge->listen_fd == server_fd) {
        bridge->listen_fd = -1;
    } else {
        should_close = false;
    }
    pthread_mutex_unlock(&bridge->mutex);
    if (should_close) {
        close(server_fd);
    }
    return NULL;
}

bool c300x_media_bridge_start(const struct c300x_config *config, struct c300x_video *video) {
    bool ok;
    pthread_t server_thread;

    pthread_mutex_lock(&g_bridge.mutex);
    if (g_bridge.running) {
        pthread_mutex_unlock(&g_bridge.mutex);
        return true;
    }
    close_fd_if_open(&g_bridge.listen_fd);
    close_all_rtsp_clients_locked(&g_bridge);
    g_bridge.config = config;
    g_bridge.video = video;
    g_bridge.listen_fd = -1;
    g_bridge.startup_done = false;
    g_bridge.startup_ok = false;
    g_bridge.running = true;
    ok = pthread_create(&g_bridge.server_thread, NULL, rtsp_server_thread, &g_bridge) == 0;
    if (!ok) {
        g_bridge.running = false;
        g_bridge.startup_done = true;
        g_bridge.startup_ok = false;
        pthread_mutex_unlock(&g_bridge.mutex);
        return false;
    }
    while (!g_bridge.startup_done) {
        pthread_cond_wait(&g_bridge.ready_cond, &g_bridge.mutex);
    }
    ok = g_bridge.startup_ok;
    server_thread = g_bridge.server_thread;
    pthread_mutex_unlock(&g_bridge.mutex);
    if (!ok) {
        pthread_join(server_thread, NULL);
        pthread_mutex_lock(&g_bridge.mutex);
        g_bridge.config = NULL;
        g_bridge.video = NULL;
        g_bridge.startup_done = false;
        g_bridge.startup_ok = false;
        pthread_mutex_unlock(&g_bridge.mutex);
    }
    return ok;
}

bool c300x_media_ring_receiver_start(const struct c300x_config *config, struct c300x_video *video) {
    bool ok;

    if (config == NULL || video == NULL || !config->video_enabled) {
        return false;
    }
    pthread_mutex_lock(&g_bridge.mutex);
    if (g_bridge.ring_started) {
        pthread_mutex_unlock(&g_bridge.mutex);
        return true;
    }
    g_bridge.config = config;
    g_bridge.video = video;
    g_bridge.ring_stop = false;
    g_bridge.ring_call_stop = false;
    g_bridge.ring_send_bye = false;
    ok = pthread_create(&g_bridge.ring_thread, NULL, ring_receiver_thread, &g_bridge) == 0;
    g_bridge.ring_started = ok;
    pthread_mutex_unlock(&g_bridge.mutex);
    return ok;
}

void c300x_media_ring_receiver_stop(struct c300x_video *video) {
    bool started;
    pthread_t ring_thread;
    int ring_sip_fd;

    pthread_mutex_lock(&g_bridge.mutex);
    if (g_bridge.video != video) {
        pthread_mutex_unlock(&g_bridge.mutex);
        return;
    }
    started = g_bridge.ring_started;
    ring_thread = g_bridge.ring_thread;
    ring_sip_fd = g_bridge.ring_sip_fd;
    g_bridge.ring_stop = true;
    g_bridge.ring_call_stop = true;
    g_bridge.ring_send_bye = true;
    pthread_cond_broadcast(&g_bridge.ready_cond);
    pthread_mutex_unlock(&g_bridge.mutex);

    if (ring_sip_fd >= 0) {
        shutdown(ring_sip_fd, SHUT_RDWR);
    }
    if (started && !pthread_equal(ring_thread, pthread_self())) {
        pthread_join(ring_thread, NULL);
    }

    pthread_mutex_lock(&g_bridge.mutex);
    close_ring_media_fds_locked(&g_bridge);
    close_fd_if_open(&g_bridge.ring_sip_fd);
    g_bridge.ring_started = false;
    g_bridge.ring_registered = false;
    g_bridge.ring_stop = false;
    g_bridge.ring_call_active = false;
    g_bridge.ring_media_active = false;
    g_bridge.ring_audio_active = false;
    g_bridge.ring_answered = false;
    g_bridge.ring_answer_requested = false;
    g_bridge.ring_call_stop = false;
    g_bridge.ring_send_bye = false;
    g_bridge.ring_srtp_state = NULL;
    reset_backchannel_talkback_locked(&g_bridge);
    if (!g_bridge.running) {
        g_bridge.config = NULL;
        g_bridge.video = NULL;
    }
    pthread_mutex_unlock(&g_bridge.mutex);
    c300x_video_bridge_media_stopped(video);
}

bool c300x_media_home_call_start(
    const struct c300x_config *config,
    struct c300x_video *video,
    int duration_seconds
) {
    bool ok;
    bool busy;

    if (
        config == NULL
        || video == NULL
        || !config->video_enabled
        || duration_seconds < 0
        || duration_seconds > C300X_HOME_CALL_MAX_DURATION_SECONDS
    ) {
        return false;
    }
    pthread_mutex_lock(&g_bridge.mutex);
    if (g_bridge.home_call_started || g_bridge.home_call_active) {
        pthread_mutex_unlock(&g_bridge.mutex);
        return true;
    }
    busy = g_bridge.media_active
        || g_bridge.media_starting
        || rtsp_client_count_locked(&g_bridge) > 0
        || g_bridge.ring_call_active
        || g_bridge.ring_media_active
        || g_bridge.ring_answer_requested
        || g_bridge.stop_in_progress;
    if (busy) {
        pthread_mutex_unlock(&g_bridge.mutex);
        c300x_video_bridge_set_error(video, "media_session_active");
        return false;
    }
    g_bridge.config = config;
    g_bridge.video = video;
    g_bridge.home_call_stop = false;
    g_bridge.home_call_send_bye = false;
    g_bridge.home_call_active = false;
    g_bridge.home_call_answered = false;
    g_bridge.home_call_rtp_proxy = false;
    g_bridge.home_call_target_audio_port = 0;
    g_bridge.home_call_duration_seconds = duration_seconds;
    g_bridge.home_call_rtp_packets = 0;
    g_bridge.home_call_rtcp_packets = 0;
    g_bridge.home_call_last_talkback_ms = 0;
    g_bridge.home_call_srtp_state = NULL;
    reset_backchannel_talkback_locked(&g_bridge);
    g_bridge.home_call_sip_fd = -1;
    g_bridge.home_call_audio_rtp_fd = -1;
    g_bridge.home_call_audio_rtcp_fd = -1;
    ok = pthread_create(&g_bridge.home_call_thread, NULL, home_call_thread_func, &g_bridge) == 0;
    g_bridge.home_call_started = ok;
    pthread_mutex_unlock(&g_bridge.mutex);
    return ok;
}

void c300x_media_home_call_stop(struct c300x_video *video) {
    bool started;
    pthread_t home_call_thread;

    pthread_mutex_lock(&g_bridge.mutex);
    if (g_bridge.video != video) {
        pthread_mutex_unlock(&g_bridge.mutex);
        return;
    }
    started = g_bridge.home_call_started;
    home_call_thread = g_bridge.home_call_thread;
    if (
        !started
        && !g_bridge.home_call_active
        && g_bridge.home_call_sip_fd < 0
        && g_bridge.home_call_audio_rtp_fd < 0
        && g_bridge.home_call_audio_rtcp_fd < 0
    ) {
        g_bridge.home_call_stop = false;
        g_bridge.home_call_send_bye = false;
        pthread_mutex_unlock(&g_bridge.mutex);
        return;
    }
    g_bridge.home_call_stop = true;
    g_bridge.home_call_send_bye = true;
    pthread_mutex_unlock(&g_bridge.mutex);

    if (started && pthread_equal(home_call_thread, pthread_self())) {
        return;
    }
    if (started) {
        pthread_join(home_call_thread, NULL);
    }

    pthread_mutex_lock(&g_bridge.mutex);
    close_home_call_fds_locked(&g_bridge);
    g_bridge.home_call_started = false;
    g_bridge.home_call_active = false;
    g_bridge.home_call_answered = false;
    g_bridge.home_call_stop = false;
    g_bridge.home_call_send_bye = false;
    g_bridge.home_call_duration_seconds = 0;
    g_bridge.home_call_last_talkback_ms = 0;
    g_bridge.home_call_srtp_state = NULL;
    reset_backchannel_talkback_locked(&g_bridge);
    if (!g_bridge.running && !g_bridge.ring_started) {
        g_bridge.config = NULL;
        g_bridge.video = NULL;
    }
    pthread_mutex_unlock(&g_bridge.mutex);
}

bool c300x_media_ring_call_active(const struct c300x_video *video) {
    bool active;

    pthread_mutex_lock(&g_bridge.mutex);
    active = g_bridge.video == video && ring_call_active_locked(&g_bridge);
    pthread_mutex_unlock(&g_bridge.mutex);
    return active;
}

void c300x_media_bridge_stop(struct c300x_video *video) {
    pthread_mutex_lock(&g_bridge.mutex);
    bool was_running = g_bridge.running;
    g_bridge.running = false;
    int listen_fd = g_bridge.listen_fd;
    g_bridge.listen_fd = -1;
    shutdown_all_rtsp_clients_locked(&g_bridge);
    pthread_mutex_unlock(&g_bridge.mutex);

    if (listen_fd >= 0) {
        shutdown(listen_fd, SHUT_RDWR);
        close(listen_fd);
    }
    pthread_mutex_lock(&g_bridge.mutex);
    while (g_bridge.rtsp_client_threads > 0) {
        pthread_cond_wait(&g_bridge.ready_cond, &g_bridge.mutex);
    }
    pthread_mutex_unlock(&g_bridge.mutex);
    c300x_media_session_stop(video);
    if (was_running) {
        pthread_join(g_bridge.server_thread, NULL);
    }
    pthread_mutex_lock(&g_bridge.mutex);
    if (!g_bridge.ring_started && !g_bridge.home_call_started && !g_bridge.home_call_active) {
        g_bridge.config = NULL;
        g_bridge.video = NULL;
    }
    g_bridge.startup_done = false;
    g_bridge.startup_ok = false;
    pthread_mutex_unlock(&g_bridge.mutex);
}
