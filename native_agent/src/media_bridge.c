#define _POSIX_C_SOURCE 200809L

#include "media_bridge.h"
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
#define SIP_USERS_FILE "/etc/flexisip/users/users.db.txt"
#define DEFAULT_SIP_PORT 5060
#define BT_AV_MEDIA_PORT 30007
#define RTSP_IDLE_TIMEOUT_SECONDS 180
#define TALKBACK_TARGET_PORT 4000
#define APP_AUDIO_RTP_PORT 26986
#define APP_AUDIO_RTCP_PORT 26987
#define APP_VIDEO_RTP_PORT 28772
#define APP_VIDEO_RTCP_PORT 28773
#define APP_MEDIA_KEEPALIVE_MS 500
#define APP_AUDIO_PACKET_MS 20
#define APP_AUDIO_TIMESTAMP_STEP 160
#define APP_AUDIO_PAYLOAD_TYPE 98
#define APP_AUDIO_SILENCE_PAYLOAD 0x00
#define APP_MEDIA_RENEW_SECONDS 20
#define APP_SIP_KEEPALIVE_SECONDS 10
#define APP_USER_AGENT "VctLinphoneService/1.17.3"
#define APP_SRTP_MASTER_KEY_LEN 30

static bool read_sip_domain(char *domain, size_t domain_len);
static int bind_udp_port(int port);
static int bind_udp_loopback_port(int port);
static void fill_random_bytes(unsigned char *out, size_t len);

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
    pthread_mutex_t mutex;
    pthread_cond_t ready_cond;
    pthread_t server_thread;
    pthread_t relay_thread;
    pthread_t sip_thread;
    pthread_t app_media_thread;
    pthread_t talkback_thread;
    bool running;
    bool startup_done;
    bool startup_ok;
    bool relay_started;
    bool sip_monitor_started;
    bool app_media_started;
    bool talkback_started;
    bool relay_stop;
    bool sip_stop;
    bool app_media_stop;
    bool talkback_stop;
    bool media_active;
    bool media_starting;
    bool stop_in_progress;
    int listen_fd;
    int client_fd;
    int rtp_fd;
    int audio_rtp_fd;
    int app_audio_rtp_fd;
    int app_audio_rtcp_fd;
    int app_video_rtp_fd;
    int app_video_rtcp_fd;
    int talkback_fd;
    int sip_fd;
    int app_target_audio_port;
    int app_target_video_port;
    unsigned char app_audio_srtp_key[APP_SRTP_MASTER_KEY_LEN];
    unsigned char app_video_srtp_key[APP_SRTP_MASTER_KEY_LEN];
    bool transport_tcp;
    bool rtsp_audio_enabled;
    int video_interleaved_channel;
    int audio_interleaved_channel;
    struct sockaddr_in udp_client;
    char session_id[32];
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
    int invite_cseq;
    const struct c300x_config *config;
    struct c300x_video *video;
} media_bridge_t;

static media_bridge_t g_bridge = {
    .mutex = PTHREAD_MUTEX_INITIALIZER,
    .ready_cond = PTHREAD_COND_INITIALIZER,
    .listen_fd = -1,
    .client_fd = -1,
    .rtp_fd = -1,
    .audio_rtp_fd = -1,
    .app_audio_rtp_fd = -1,
    .app_audio_rtcp_fd = -1,
    .app_video_rtp_fd = -1,
    .app_video_rtcp_fd = -1,
    .sip_fd = -1,
    .talkback_fd = -1,
    .video_interleaved_channel = 2,
    .audio_interleaved_channel = 0,
};

static void close_fd_if_open(int *fd) {
    if (fd != NULL && *fd >= 0) {
        close(*fd);
        *fd = -1;
    }
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
    void (*crypto_policy_set_rtp_default)(c300x_srtp_crypto_policy_t *policy);
    void (*crypto_policy_set_rtcp_default)(c300x_srtp_crypto_policy_t *policy);
} c300x_srtp_api_t;

typedef struct {
    c300x_srtp_t audio;
    c300x_srtp_t video;
    uint16_t audio_seq;
    uint32_t audio_timestamp;
    uint32_t audio_ssrc;
    uint32_t rtcp_sender_ssrc;
    int available;
} app_srtp_state_t;

static pthread_mutex_t g_srtp_mutex = PTHREAD_MUTEX_INITIALIZER;
static c300x_srtp_api_t g_srtp_api;

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

static int app_srtp_init_state(
    app_srtp_state_t *state,
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

static void app_srtp_deinit_state(app_srtp_state_t *state) {
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
    memset(state, 0, sizeof(*state));
}

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

static bool split_sip_aor(
    const char *aor,
    char *user,
    size_t user_len,
    char *host,
    size_t host_len
) {
    const char *body = aor;
    const char *at;
    size_t user_size;
    size_t host_size;

    if (strncasecmp(body, "sip:", 4) == 0) {
        body += 4;
    }
    if (!sip_string_is_safe(body)) {
        return false;
    }
    at = strchr(body, '@');
    if (at == NULL || at == body || at[1] == '\0') {
        return false;
    }
    user_size = (size_t)(at - body);
    host_size = strlen(at + 1);
    if (user_size >= user_len || host_size >= host_len) {
        return false;
    }
    memcpy(user, body, user_size);
    user[user_size] = '\0';
    memcpy(host, at + 1, host_size);
    host[host_size] = '\0';
    return sip_string_is_safe(user) && sip_string_is_safe(host);
}

static bool sip_aor_starts_with_user(const char *aor, const char *user) {
    const char *body = aor;
    size_t user_len = strlen(user);

    if (strncasecmp(body, "sip:", 4) == 0) {
        body += 4;
    }
    return strncmp(body, user, user_len) == 0 && body[user_len] == '@';
}

static bool first_token(char *line, char *out, size_t out_len) {
    char *start = line;
    size_t len = 0;

    while (*start == ' ' || *start == '\t') {
        start++;
    }
    while (
        start[len] != '\0'
        && start[len] != ' '
        && start[len] != '\t'
        && start[len] != '\r'
        && start[len] != '\n'
    ) {
        len++;
    }
    if (len == 0 || len >= out_len) {
        return false;
    }
    memcpy(out, start, len);
    out[len] = '\0';
    return sip_string_is_safe(out);
}

static bool app_identity_from_flexisip(
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
    FILE *fp = fopen(SIP_USERS_FILE, "r");
    char line[512];
    char token[256];
    char app_aor[256] = "";
    char device_domain[128] = "";
    char app_host[128];

    if (fp == NULL) {
        return false;
    }
    while (fgets(line, sizeof(line), fp) != NULL) {
        if (!first_token(line, token, sizeof(token)) || strchr(token, '@') == NULL) {
            continue;
        }
        if (sip_aor_starts_with_user(token, "c300x")) {
            char device_user[128];
            (void)split_sip_aor(token, device_user, sizeof(device_user), device_domain, sizeof(device_domain));
        } else if (app_aor[0] == '\0') {
            snprintf(app_aor, sizeof(app_aor), "%s", token);
        }
    }
    fclose(fp);

    if (app_aor[0] == '\0') {
        return false;
    }
    if (!split_sip_aor(app_aor, from_user, from_user_len, app_host, sizeof(app_host))) {
        return false;
    }
    if (device_domain[0] != '\0') {
        if (!copy_checked(domain, domain_len, device_domain)) {
            return false;
        }
    } else if (domain_hint != NULL && domain_hint[0] != '\0') {
        if (!copy_checked(domain, domain_len, domain_hint)) {
            return false;
        }
    } else if (!copy_checked(domain, domain_len, app_host)) {
        return false;
    }
    if (!sip_string_is_safe(domain)) {
        return false;
    }
    return snprintf(from_aor, from_aor_len, "%s@%s", from_user, domain) < (int)from_aor_len
        && snprintf(to_aor, to_aor_len, "c300x@%s", domain) < (int)to_aor_len;
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

static bool generate_sdes_key(unsigned char *key, size_t key_len, char *out, size_t out_len) {
    if (key == NULL || key_len != APP_SRTP_MASTER_KEY_LEN) {
        return false;
    }
    fill_random_bytes(key, key_len);
    return base64_encode(key, key_len, out, out_len);
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
    char via[512];
    char to[512];
    char from[512];
    char call_id[128];
    char cseq[64];
    char response[2048];

    header_value(message, "Via:", via, sizeof(via));
    header_value(message, "To:", to, sizeof(to));
    header_value(message, "From:", from, sizeof(from));
    header_value(message, "Call-ID:", call_id, sizeof(call_id));
    header_value(message, "CSeq:", cseq, sizeof(cseq));
    if (via[0] == '\0' || to[0] == '\0' || from[0] == '\0' || call_id[0] == '\0' || cseq[0] == '\0') {
        return;
    }

    snprintf(
        response,
        sizeof(response),
        "SIP/2.0 200 OK\r\n"
        "Via: %s\r\n"
        "To: %s\r\n"
        "From: %s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: %s\r\n"
        "Content-Length: 0\r\n\r\n",
        via,
        to,
        from,
        call_id,
        cseq
    );
    (void)send_all(fd, response, strlen(response));
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
            int client_fd = bridge->client_fd;
            bridge->relay_stop = true;
            pthread_mutex_unlock(&bridge->mutex);
            if (client_fd >= 0) {
                shutdown(client_fd, SHUT_RDWR);
            }
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

static void send_app_audio_silence(int fd, int port, app_srtp_state_t *state) {
    unsigned char packet[64];

    if (state == NULL || !state->available) {
        return;
    }
    memset(packet, 0, sizeof(packet));
    packet[0] = 0x80;
    packet[1] = APP_AUDIO_PAYLOAD_TYPE;
    store_be16(packet + 2, state->audio_seq);
    store_be32(packet + 4, state->audio_timestamp);
    store_be32(packet + 8, state->audio_ssrc);
    packet[12] = APP_AUDIO_SILENCE_PAYLOAD;
    if (protect_and_send_srtp(state->audio, fd, port, packet, 13)) {
        state->audio_seq++;
        state->audio_timestamp += APP_AUDIO_TIMESTAMP_STEP;
    }
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

static void drain_app_media_socket(int fd, uint32_t *video_ssrc) {
    unsigned char packet[2048];
    struct sockaddr_in from;
    socklen_t from_len = sizeof(from);
    ssize_t n;

    if (fd < 0) {
        return;
    }
    while ((n = recvfrom(fd, packet, sizeof(packet), MSG_DONTWAIT, (struct sockaddr *)&from, &from_len)) > 0) {
        if (video_ssrc != NULL && n >= 12 && (packet[0] & 0xc0) == 0x80) {
            *video_ssrc = ((uint32_t)packet[8] << 24)
                | ((uint32_t)packet[9] << 16)
                | ((uint32_t)packet[10] << 8)
                | (uint32_t)packet[11];
        }
        from_len = sizeof(from);
    }
}

static void *app_media_thread(void *arg) {
    media_bridge_t *bridge = arg;
    uint32_t video_ssrc = 0;
    unsigned char audio_key[APP_SRTP_MASTER_KEY_LEN];
    unsigned char video_key[APP_SRTP_MASTER_KEY_LEN];
    app_srtp_state_t srtp;
    long long next_media_keepalive = 0;
    long long next_audio_rtp = 0;
    long long next_rtcp = 0;
    long long next_sip_keepalive = 0;
    long long next_bt_av_renew = monotonic_ms() + ((long long)APP_MEDIA_RENEW_SECONDS * 1000LL);

    pthread_mutex_lock(&bridge->mutex);
    memcpy(audio_key, bridge->app_audio_srtp_key, sizeof(audio_key));
    memcpy(video_key, bridge->app_video_srtp_key, sizeof(video_key));
    pthread_mutex_unlock(&bridge->mutex);
    if (!app_srtp_init_state(&srtp, audio_key, video_key)) {
        secure_zero(audio_key, sizeof(audio_key));
        secure_zero(video_key, sizeof(video_key));
        pthread_mutex_lock(&bridge->mutex);
        bridge->app_media_started = false;
        if (bridge->app_audio_rtp_fd >= 0) {
            close(bridge->app_audio_rtp_fd);
            bridge->app_audio_rtp_fd = -1;
        }
        if (bridge->app_audio_rtcp_fd >= 0) {
            close(bridge->app_audio_rtcp_fd);
            bridge->app_audio_rtcp_fd = -1;
        }
        if (bridge->app_video_rtp_fd >= 0) {
            close(bridge->app_video_rtp_fd);
            bridge->app_video_rtp_fd = -1;
        }
        if (bridge->app_video_rtcp_fd >= 0) {
            close(bridge->app_video_rtcp_fd);
            bridge->app_video_rtcp_fd = -1;
        }
        pthread_mutex_unlock(&bridge->mutex);
        return NULL;
    }
    secure_zero(audio_key, sizeof(audio_key));
    secure_zero(video_key, sizeof(video_key));

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
        stop = bridge->app_media_stop || bridge->sip_stop;
        sip_fd = bridge->sip_fd;
        audio_rtp_fd = bridge->app_audio_rtp_fd;
        audio_rtcp_fd = bridge->app_audio_rtcp_fd;
        video_rtp_fd = bridge->app_video_rtp_fd;
        video_rtcp_fd = bridge->app_video_rtcp_fd;
        target_audio_port = bridge->app_target_audio_port;
        target_video_port = bridge->app_target_video_port;
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

        struct timeval timeout = {0, APP_AUDIO_PACKET_MS * 1000};
        if (max_fd >= 0 && select(max_fd + 1, &readfds, NULL, NULL, &timeout) > 0) {
            if (audio_rtp_fd >= 0 && FD_ISSET(audio_rtp_fd, &readfds)) {
                drain_app_media_socket(audio_rtp_fd, NULL);
            }
            if (audio_rtcp_fd >= 0 && FD_ISSET(audio_rtcp_fd, &readfds)) {
                drain_app_media_socket(audio_rtcp_fd, NULL);
            }
            if (video_rtp_fd >= 0 && FD_ISSET(video_rtp_fd, &readfds)) {
                drain_app_media_socket(video_rtp_fd, &video_ssrc);
            }
            if (video_rtcp_fd >= 0 && FD_ISSET(video_rtcp_fd, &readfds)) {
                drain_app_media_socket(video_rtcp_fd, NULL);
            }
        }

        long long now = monotonic_ms();
        if (next_media_keepalive == 0 || now >= next_media_keepalive) {
            send_stun_binding_request(audio_rtp_fd, target_audio_port);
            send_stun_binding_request(audio_rtcp_fd, target_audio_port + 1);
            send_stun_binding_request(video_rtp_fd, target_video_port);
            send_stun_binding_request(video_rtcp_fd, target_video_port + 1);
            next_media_keepalive = now + APP_MEDIA_KEEPALIVE_MS;
        }
        if (next_audio_rtp == 0 || now >= next_audio_rtp) {
            send_app_audio_silence(audio_rtp_fd, target_audio_port, &srtp);
            next_audio_rtp = now + APP_AUDIO_PACKET_MS;
        }
        if (next_rtcp == 0 || now >= next_rtcp) {
            send_srtcp_receiver_report(audio_rtcp_fd, target_audio_port + 1, srtp.audio, srtp.audio_ssrc);
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
            next_sip_keepalive = now + ((long long)APP_SIP_KEEPALIVE_SECONDS * 1000LL);
        }
        if (next_bt_av_renew == 0 || now >= next_bt_av_renew) {
            (void)start_bt_av_media(bridge);
            next_bt_av_renew = now + ((long long)APP_MEDIA_RENEW_SECONDS * 1000LL);
        }
    }

    pthread_mutex_lock(&bridge->mutex);
    if (bridge->app_audio_rtp_fd >= 0) {
        close(bridge->app_audio_rtp_fd);
        bridge->app_audio_rtp_fd = -1;
    }
    if (bridge->app_audio_rtcp_fd >= 0) {
        close(bridge->app_audio_rtcp_fd);
        bridge->app_audio_rtcp_fd = -1;
    }
    if (bridge->app_video_rtp_fd >= 0) {
        close(bridge->app_video_rtp_fd);
        bridge->app_video_rtp_fd = -1;
    }
    if (bridge->app_video_rtcp_fd >= 0) {
        close(bridge->app_video_rtcp_fd);
        bridge->app_video_rtcp_fd = -1;
    }
    bridge->app_media_started = false;
    pthread_mutex_unlock(&bridge->mutex);
    app_srtp_deinit_state(&srtp);
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
    int app_audio_rtp_fd = -1;
    int app_audio_rtcp_fd = -1;
    int app_video_rtp_fd = -1;
    int app_video_rtcp_fd = -1;
    int target_audio_port = 7078;
    int target_video_port = 9078;
    unsigned char audio_key_raw[APP_SRTP_MASTER_KEY_LEN];
    unsigned char video_key_raw[APP_SRTP_MASTER_KEY_LEN];
    char audio_key[64];
    char video_key[64];

    (void)sip_domain_from_config(bridge->config, domain_hint, sizeof(domain_hint));
    if (
        !app_identity_from_flexisip(
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

    app_audio_rtp_fd = bind_udp_loopback_port(APP_AUDIO_RTP_PORT);
    app_audio_rtcp_fd = bind_udp_loopback_port(APP_AUDIO_RTCP_PORT);
    app_video_rtp_fd = bind_udp_loopback_port(APP_VIDEO_RTP_PORT);
    app_video_rtcp_fd = bind_udp_loopback_port(APP_VIDEO_RTCP_PORT);
    if (app_audio_rtp_fd < 0 || app_audio_rtcp_fd < 0 || app_video_rtp_fd < 0 || app_video_rtcp_fd < 0) {
        if (app_audio_rtp_fd >= 0) {
            close(app_audio_rtp_fd);
        }
        if (app_audio_rtcp_fd >= 0) {
            close(app_audio_rtcp_fd);
        }
        if (app_video_rtp_fd >= 0) {
            close(app_video_rtp_fd);
        }
        if (app_video_rtcp_fd >= 0) {
            close(app_video_rtcp_fd);
        }
        return false;
    }

    int fd = connect_sip_socket(bridge->config);
    if (fd < 0) {
        close(app_audio_rtp_fd);
        close(app_audio_rtcp_fd);
        close(app_video_rtp_fd);
        close(app_video_rtcp_fd);
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
    ) {
        secure_zero(audio_key_raw, sizeof(audio_key_raw));
        secure_zero(video_key_raw, sizeof(video_key_raw));
        close(fd);
        close(app_audio_rtp_fd);
        close(app_audio_rtcp_fd);
        close(app_video_rtp_fd);
        close(app_video_rtcp_fd);
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
        "Contact: <sip:%s;transport=%s>;expires=300;+sip.instance=\"<urn:uuid:19609c0e-f27b-7595-e9c8269557c4240b>\"\r\n"
        "User-Agent: " APP_USER_AGENT "\r\n"
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
        transport
    );
    if (send_all(fd, request, strlen(request)) <= 0 || read_message(fd, response, sizeof(response), 3) < 0) {
        secure_zero(audio_key_raw, sizeof(audio_key_raw));
        secure_zero(video_key_raw, sizeof(video_key_raw));
        close(fd);
        close(app_audio_rtp_fd);
        close(app_audio_rtcp_fd);
        close(app_video_rtp_fd);
        close(app_video_rtcp_fd);
        return false;
    }
    if (sip_status_code(response) >= 300) {
        secure_zero(audio_key_raw, sizeof(audio_key_raw));
        secure_zero(video_key_raw, sizeof(video_key_raw));
        close(fd);
        close(app_audio_rtp_fd);
        close(app_audio_rtcp_fd);
        close(app_video_rtp_fd);
        close(app_video_rtcp_fd);
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
        "a=rtpmap:0 PCMU/8000\r\n"
        "a=rtpmap:8 PCMA/8000\r\n"
        "a=rtpmap:101 telephone-event/48000\r\n"
        "a=rtpmap:99 telephone-event/16000\r\n"
        "a=rtpmap:100 telephone-event/8000\r\n"
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:%s\r\n"
        "a=rtcp-fb:* trr-int 1000\r\n"
        "a=rtcp-fb:* ccm tmmbr\r\n"
        "m=video %d RTP/SAVP 96 97 98 99\r\n"
        "a=rtpmap:97 VP8/90000\r\n"
        "a=rtpmap:98 H264/90000\r\n"
        "a=fmtp:98 profile-level-id=42801F\r\n"
        "a=rtpmap:99 H265/90000\r\n"
        "a=recvonly\r\n",
        from_user,
        local_ip,
        local_ip,
        doorbell_devaddr(bridge->config),
        APP_AUDIO_RTP_PORT,
        audio_key,
        APP_VIDEO_RTP_PORT
    );
    size_t sdp_used = strlen(sdp);
    snprintf(
        sdp + sdp_used,
        sizeof(sdp) - sdp_used,
        "a=crypto:2 AES_CM_128_HMAC_SHA1_80 inline:%s\r\n"
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
        video_key
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
        "User-Agent: " APP_USER_AGENT "\r\n"
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
        close(app_audio_rtp_fd);
        close(app_audio_rtcp_fd);
        close(app_video_rtp_fd);
        close(app_video_rtcp_fd);
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
        close(fd);
        close(app_audio_rtp_fd);
        close(app_audio_rtcp_fd);
        close(app_video_rtp_fd);
        close(app_video_rtcp_fd);
        return false;
    }
    target_audio_port = parse_sdp_media_port(response, "\r\nm=audio ", target_audio_port);
    target_video_port = parse_sdp_media_port(response, "\r\nm=video ", target_video_port);

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
    bridge->app_media_stop = false;
    bridge->app_audio_rtp_fd = app_audio_rtp_fd;
    bridge->app_audio_rtcp_fd = app_audio_rtcp_fd;
    bridge->app_video_rtp_fd = app_video_rtp_fd;
    bridge->app_video_rtcp_fd = app_video_rtcp_fd;
    bridge->app_target_audio_port = target_audio_port;
    bridge->app_target_video_port = target_video_port;
    memcpy(bridge->app_audio_srtp_key, audio_key_raw, sizeof(bridge->app_audio_srtp_key));
    memcpy(bridge->app_video_srtp_key, video_key_raw, sizeof(bridge->app_video_srtp_key));
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
    bridge->app_media_started = pthread_create(&bridge->app_media_thread, NULL, app_media_thread, bridge) == 0;
    bool monitor_started = bridge->sip_monitor_started;
    bool app_media_started = bridge->app_media_started;
    pthread_mutex_unlock(&bridge->mutex);
    secure_zero(audio_key_raw, sizeof(audio_key_raw));
    secure_zero(video_key_raw, sizeof(video_key_raw));
    return monitor_started && app_media_started;
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

static void *rtp_relay_thread(void *arg) {
    media_bridge_t *bridge = arg;
    unsigned char packet[2048];

    while (true) {
        pthread_mutex_lock(&bridge->mutex);
        bool stop = bridge->relay_stop;
        int rtp_fd = bridge->rtp_fd;
        int audio_rtp_fd = bridge->audio_rtp_fd;
        int client_fd = bridge->client_fd;
        bool transport_tcp = bridge->transport_tcp;
        int video_channel = bridge->video_interleaved_channel;
        int audio_channel = bridge->audio_interleaved_channel;
        struct sockaddr_in udp_client = bridge->udp_client;
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
            if (n > 0 && client_fd >= 0) {
                c300x_video_bridge_rtp_packet(bridge->video);
                if (transport_tcp) {
                    unsigned char frame_header[4];
                    frame_header[0] = '$';
                    frame_header[1] = (unsigned char)audio_channel;
                    frame_header[2] = (unsigned char)(((unsigned)n >> 8) & 0xff);
                    frame_header[3] = (unsigned char)((unsigned)n & 0xff);
                    if (send_all(client_fd, frame_header, sizeof(frame_header)) <= 0 || send_all(client_fd, packet, (size_t)n) <= 0) {
                        break;
                    }
                } else {
                    (void)sendto(client_fd, packet, (size_t)n, 0, (struct sockaddr *)&udp_client, sizeof(udp_client));
                }
            }
        }
        if (!FD_ISSET(rtp_fd, &readfds)) {
            continue;
        }

        ssize_t n = recv(rtp_fd, packet, sizeof(packet), 0);
        if (n <= 0) {
            continue;
        }
        c300x_video_bridge_rtp_packet(bridge->video);
        if (client_fd < 0) {
            continue;
        }

        if (transport_tcp) {
            unsigned char frame_header[4];
            frame_header[0] = '$';
            frame_header[1] = (unsigned char)video_channel;
            frame_header[2] = (unsigned char)(((unsigned)n >> 8) & 0xff);
            frame_header[3] = (unsigned char)((unsigned)n & 0xff);
            if (send_all(client_fd, frame_header, sizeof(frame_header)) <= 0 || send_all(client_fd, packet, (size_t)n) <= 0) {
                break;
            }
        } else {
            (void)sendto(client_fd, packet, (size_t)n, 0, (struct sockaddr *)&udp_client, sizeof(udp_client));
        }
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
            (void)sendto(target_fd, packet, (size_t)n, 0, (struct sockaddr *)&target, sizeof(target));
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

static void stop_media_session(bool close_client);

static bool start_media_session(media_bridge_t *bridge) {
    pthread_mutex_lock(&bridge->mutex);
    if (bridge->media_active || bridge->media_starting) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }
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

    if (!send_sip_setup(bridge)) {
        c300x_video_bridge_set_error(bridge->video, "app_sip_setup_failed");
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
    bool app_media_started = false;
    bool talkback_started = false;
    bool send_media_stop = false;
    pthread_t sip_thread;
    pthread_t app_media_thread_id;
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
    int client_fd = g_bridge.client_fd;
    if (g_bridge.stop_in_progress) {
        pthread_mutex_unlock(&g_bridge.mutex);
        if (close_client && client_fd >= 0) {
            shutdown(client_fd, SHUT_RDWR);
        }
        return;
    }
    if (
        !g_bridge.media_active
        && !g_bridge.media_starting
        && !g_bridge.relay_started
        && !g_bridge.sip_monitor_started
        && !g_bridge.app_media_started
        && !g_bridge.talkback_started
        && g_bridge.rtp_fd < 0
        && g_bridge.audio_rtp_fd < 0
        && g_bridge.app_audio_rtp_fd < 0
        && g_bridge.app_audio_rtcp_fd < 0
        && g_bridge.app_video_rtp_fd < 0
        && g_bridge.app_video_rtcp_fd < 0
        && g_bridge.sip_fd < 0
        && g_bridge.talkback_fd < 0
    ) {
        pthread_mutex_unlock(&g_bridge.mutex);
        if (close_client && client_fd >= 0) {
            shutdown(client_fd, SHUT_RDWR);
        }
        return;
    }
    g_bridge.stop_in_progress = true;
    g_bridge.relay_stop = true;
    g_bridge.sip_stop = true;
    g_bridge.app_media_stop = true;
    g_bridge.talkback_stop = true;
    send_media_stop = g_bridge.media_active || g_bridge.relay_started;
    relay_started = g_bridge.relay_started;
    sip_monitor_started = g_bridge.sip_monitor_started;
    app_media_started = g_bridge.app_media_started;
    talkback_started = g_bridge.talkback_started;
    sip_thread = g_bridge.sip_thread;
    app_media_thread_id = g_bridge.app_media_thread;
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
    pthread_mutex_unlock(&g_bridge.mutex);

    if (close_client && client_fd >= 0) {
        shutdown(client_fd, SHUT_RDWR);
    }

    if (relay_started) {
        pthread_join(g_bridge.relay_thread, NULL);
    }
    if (talkback_started) {
        pthread_join(talkback_thread, NULL);
    }
    if (app_media_started && !pthread_equal(app_media_thread_id, pthread_self())) {
        pthread_join(app_media_thread_id, NULL);
    }

    if (send_media_stop) {
        send_bt_av_media_stop();
    }
    if (sip_fd >= 0) {
        send_sip_bye(sip_fd, from_aor, to_aor, local_ip, local_port, transport, to_header, from_tag, call_id, contact_uri);
    }
    if (sip_fd >= 0) {
        shutdown(sip_fd, SHUT_RDWR);
    }
    if (sip_monitor_started && !pthread_equal(sip_thread, pthread_self())) {
        pthread_join(sip_thread, NULL);
    }
    if (sip_fd >= 0) {
        close(sip_fd);
    }

    pthread_mutex_lock(&g_bridge.mutex);
    g_bridge.media_active = false;
    g_bridge.media_starting = false;
    g_bridge.sip_stop = false;
    g_bridge.app_media_stop = false;
    g_bridge.talkback_stop = false;
    g_bridge.sip_monitor_started = false;
    g_bridge.app_media_started = false;
    if (g_bridge.rtp_fd >= 0) {
        close(g_bridge.rtp_fd);
        g_bridge.rtp_fd = -1;
    }
    if (g_bridge.audio_rtp_fd >= 0) {
        close(g_bridge.audio_rtp_fd);
        g_bridge.audio_rtp_fd = -1;
    }
    if (g_bridge.app_audio_rtp_fd >= 0) {
        close(g_bridge.app_audio_rtp_fd);
        g_bridge.app_audio_rtp_fd = -1;
    }
    if (g_bridge.app_audio_rtcp_fd >= 0) {
        close(g_bridge.app_audio_rtcp_fd);
        g_bridge.app_audio_rtcp_fd = -1;
    }
    if (g_bridge.app_video_rtp_fd >= 0) {
        close(g_bridge.app_video_rtp_fd);
        g_bridge.app_video_rtp_fd = -1;
    }
    if (g_bridge.app_video_rtcp_fd >= 0) {
        close(g_bridge.app_video_rtcp_fd);
        g_bridge.app_video_rtcp_fd = -1;
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
    g_bridge.app_target_audio_port = 0;
    g_bridge.app_target_video_port = 0;
    memset(g_bridge.app_audio_srtp_key, 0, sizeof(g_bridge.app_audio_srtp_key));
    memset(g_bridge.app_video_srtp_key, 0, sizeof(g_bridge.app_video_srtp_key));
    g_bridge.stop_in_progress = false;
    pthread_mutex_unlock(&g_bridge.mutex);
}

void c300x_media_session_stop(struct c300x_video *video) {
    (void)video;
    stop_media_session(true);
    c300x_video_bridge_media_stopped(g_bridge.video);
}

bool c300x_media_session_warmup(struct c300x_video *video) {
    pthread_mutex_lock(&g_bridge.mutex);
    bool ready = g_bridge.running && g_bridge.config != NULL && g_bridge.video == video;
    pthread_mutex_unlock(&g_bridge.mutex);
    if (!ready) {
        return false;
    }
    return start_media_session(&g_bridge);
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

bool c300x_media_session_renew(struct c300x_video *video) {
    bool ready;
    bool active;

    pthread_mutex_lock(&g_bridge.mutex);
    ready = g_bridge.running && g_bridge.config != NULL && g_bridge.video == video;
    active = g_bridge.media_active;
    pthread_mutex_unlock(&g_bridge.mutex);

    if (!ready) {
        return false;
    }
    if (!active) {
        return start_media_session(&g_bridge);
    }
    c300x_video_bridge_media_started(g_bridge.video, true);
    return true;
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
        status->bridge_media_active = g_bridge.media_active ? 1 : 0;
        status->bridge_stop_in_progress = g_bridge.stop_in_progress ? 1 : 0;
        open_fds += g_bridge.listen_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.client_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.rtp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.audio_rtp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.app_audio_rtp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.app_audio_rtcp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.app_video_rtp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.app_video_rtcp_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.talkback_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.sip_fd >= 0 ? 1 : 0;
        active_threads += g_bridge.running ? 1 : 0;
        active_threads += g_bridge.relay_started ? 1 : 0;
        active_threads += g_bridge.sip_monitor_started ? 1 : 0;
        active_threads += g_bridge.app_media_started ? 1 : 0;
        active_threads += g_bridge.talkback_started ? 1 : 0;
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

static void send_rtsp_response(int fd, int status, const char *cseq, const char *headers, const char *body) {
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
    char request[RTSP_BUFFER_SIZE];
    char method[16];
    char uri[512];
    char cseq[64];
    char transport[512];
    bool media_started = false;
    bool busy = false;

    pthread_mutex_lock(&g_bridge.mutex);
    busy = g_bridge.client_fd >= 0 && g_bridge.client_fd != fd;
    if (!busy) {
        g_bridge.client_fd = fd;
        snprintf(g_bridge.session_id, sizeof(g_bridge.session_id), "%ld", (long)time(NULL));
    }
    pthread_mutex_unlock(&g_bridge.mutex);
    if (busy) {
        send_rtsp_response(fd, 453, "1", NULL, NULL);
        close(fd);
        return;
    }
    c300x_video_bridge_client_connected(g_bridge.video);

    while (g_bridge.running) {
        if (read_message(fd, request, sizeof(request), media_started ? RTSP_IDLE_TIMEOUT_SECONDS : 30) < 0) {
            break;
        }
        method[0] = '\0';
        uri[0] = '\0';
        cseq[0] = '\0';
        transport[0] = '\0';
        (void)sscanf(request, "%15s %511s", method, uri);
        header_value(request, "CSeq:", cseq, sizeof(cseq));
        header_value(request, "Transport:", transport, sizeof(transport));

        if (strcmp(method, "OPTIONS") == 0) {
            send_rtsp_response(fd, 200, cseq, "Public: OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN, GET_PARAMETER\r\n", NULL);
        } else if (strcmp(method, "DESCRIBE") == 0) {
            bool wants_audio = strstr(uri, "/doorbell") != NULL && strstr(uri, "/doorbell-video") == NULL && strstr(uri, "/doorbell-recorder") == NULL;
            pthread_mutex_lock(&g_bridge.mutex);
            g_bridge.rtsp_audio_enabled = wants_audio;
            g_bridge.video_interleaved_channel = wants_audio ? 2 : 0;
            g_bridge.audio_interleaved_channel = 0;
            pthread_mutex_unlock(&g_bridge.mutex);
            const char *sdp_audio_video =
                "v=0\r\n"
                "o=- 0 0 IN IP4 127.0.0.1\r\n"
                "s=BTicino Doorbell\r\n"
                "c=IN IP4 0.0.0.0\r\n"
                "t=0 0\r\n"
                "m=audio 0 RTP/AVP 110\r\n"
                "a=rtpmap:110 speex/8000\r\n"
                "a=control:streamid=0\r\n"
                "m=video 0 RTP/AVP 96\r\n"
                "a=rtpmap:96 H264/90000\r\n"
                "a=control:streamid=1\r\n";
            const char *sdp_video =
                "v=0\r\n"
                "o=- 0 0 IN IP4 127.0.0.1\r\n"
                "s=BTicino Doorbell\r\n"
                "c=IN IP4 0.0.0.0\r\n"
                "t=0 0\r\n"
                "m=video 0 RTP/AVP 96\r\n"
                "a=rtpmap:96 H264/90000\r\n"
                "a=control:streamid=1\r\n";
            const char *sdp = wants_audio ? sdp_audio_video : sdp_video;
            char headers[512];
            snprintf(headers, sizeof(headers), "Content-Type: application/sdp\r\nContent-Base: %s/\r\n", uri);
            send_rtsp_response(fd, 200, cseq, headers, sdp);
        } else if (strcmp(method, "SETUP") == 0) {
            bool tcp = strstr(transport, "RTP/AVP/TCP") != NULL;
            int client_port = parse_client_port(transport);
            int interleaved_channel = parse_interleaved_channel(transport);
            pthread_mutex_lock(&g_bridge.mutex);
            bool rtsp_audio_enabled = g_bridge.rtsp_audio_enabled;
            pthread_mutex_unlock(&g_bridge.mutex);
            bool is_audio = rtsp_audio_enabled && strstr(uri, "streamid=0") != NULL;
            int server_port = is_audio ? audio_rtp_port(g_bridge.config) : video_rtp_port(g_bridge.config);
            if (interleaved_channel < 0) {
                interleaved_channel = is_audio ? 0 : (rtsp_audio_enabled ? 2 : 0);
            }
            pthread_mutex_lock(&g_bridge.mutex);
            g_bridge.transport_tcp = tcp;
            if (is_audio) {
                g_bridge.audio_interleaved_channel = interleaved_channel;
            } else {
                g_bridge.video_interleaved_channel = interleaved_channel;
            }
            memset(&g_bridge.udp_client, 0, sizeof(g_bridge.udp_client));
            if (!tcp && client_port > 0 && rtsp_peer_ipv4_address(peer, &g_bridge.udp_client.sin_addr)) {
                g_bridge.udp_client.sin_family = AF_INET;
                g_bridge.udp_client.sin_port = htons((uint16_t)client_port);
            }
            pthread_mutex_unlock(&g_bridge.mutex);

            char headers[512];
            if (tcp) {
                snprintf(
                    headers,
                    sizeof(headers),
                    "Transport: RTP/AVP/TCP;unicast;interleaved=%d-%d;ssrc=1A2B3C4D\r\nSession: %s;timeout=%d\r\n",
                    interleaved_channel,
                    interleaved_channel + 1,
                    g_bridge.session_id,
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
                    g_bridge.session_id,
                    RTSP_IDLE_TIMEOUT_SECONDS
                );
            }
            send_rtsp_response(fd, 200, cseq, headers, NULL);
        } else if (strcmp(method, "PLAY") == 0) {
            if (!start_media_session(&g_bridge)) {
                send_rtsp_response(fd, 500, cseq, NULL, NULL);
                break;
            }
            media_started = true;
            char headers[256];
            snprintf(headers, sizeof(headers), "Session: %s\r\nRTP-Info: url=%s/streamid=1;seq=0;rtptime=0\r\n", g_bridge.session_id, uri);
            send_rtsp_response(fd, 200, cseq, headers, NULL);
        } else if (strcmp(method, "GET_PARAMETER") == 0) {
            char headers[128];
            snprintf(headers, sizeof(headers), "Session: %s\r\n", g_bridge.session_id);
            send_rtsp_response(fd, 200, cseq, headers, NULL);
        } else if (strcmp(method, "TEARDOWN") == 0) {
            char headers[128];
            snprintf(headers, sizeof(headers), "Session: %s\r\n", g_bridge.session_id);
            send_rtsp_response(fd, 200, cseq, headers, NULL);
            break;
        } else {
            send_rtsp_response(fd, 404, cseq, NULL, NULL);
        }
    }

    if (media_started) {
        c300x_media_session_stop(g_bridge.video);
        c300x_video_bridge_media_stopped(g_bridge.video);
    }
    pthread_mutex_lock(&g_bridge.mutex);
    if (g_bridge.client_fd == fd) {
        g_bridge.client_fd = -1;
    }
    pthread_mutex_unlock(&g_bridge.mutex);
    c300x_video_bridge_client_disconnected(g_bridge.video);
    close(fd);
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
        handle_rtsp_client(client_fd, &peer);
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
    close_fd_if_open(&g_bridge.client_fd);
    g_bridge.config = config;
    g_bridge.video = video;
    g_bridge.listen_fd = -1;
    g_bridge.client_fd = -1;
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

void c300x_media_bridge_stop(struct c300x_video *video) {
    pthread_mutex_lock(&g_bridge.mutex);
    bool was_running = g_bridge.running;
    g_bridge.running = false;
    int listen_fd = g_bridge.listen_fd;
    int client_fd = g_bridge.client_fd;
    g_bridge.listen_fd = -1;
    g_bridge.client_fd = -1;
    pthread_mutex_unlock(&g_bridge.mutex);

    if (listen_fd >= 0) {
        shutdown(listen_fd, SHUT_RDWR);
        close(listen_fd);
    }
    if (client_fd >= 0) {
        shutdown(client_fd, SHUT_RDWR);
    }
    c300x_media_session_stop(video);
    if (was_running) {
        pthread_join(g_bridge.server_thread, NULL);
    }
    pthread_mutex_lock(&g_bridge.mutex);
    g_bridge.config = NULL;
    g_bridge.video = NULL;
    g_bridge.startup_done = false;
    g_bridge.startup_ok = false;
    pthread_mutex_unlock(&g_bridge.mutex);
}
