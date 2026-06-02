#define _POSIX_C_SOURCE 200809L

#include "media_bridge.h"
#include "video_rtsp.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "pthread_compat.h"

#define RTSP_BUFFER_SIZE 8192
#define SIP_BUFFER_SIZE 8192
#define SIP_DOMAIN_FILE "/etc/flexisip/domain-registration.conf"
#define FLEXISIP_INIT_SCRIPT "/etc/init.d/flexisipsh"
#define SIP_PORT 5060
#define BT_AV_MEDIA_PORT 30007
#define RTSP_IDLE_TIMEOUT_SECONDS 180
#define TALKBACK_TARGET_PORT 4000

static bool sip_video_call_enabled(void) {
    return true;
}

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
    pthread_t talkback_thread;
    bool running;
    bool startup_done;
    bool startup_ok;
    bool relay_started;
    bool sip_monitor_started;
    bool talkback_started;
    bool relay_stop;
    bool sip_stop;
    bool talkback_stop;
    bool sip_proxy_started_by_agent;
    bool media_active;
    bool media_starting;
    bool stop_in_progress;
    int listen_fd;
    int client_fd;
    int rtp_fd;
    int audio_rtp_fd;
    int talkback_fd;
    int sip_fd;
    bool transport_tcp;
    bool rtsp_audio_enabled;
    int video_interleaved_channel;
    int audio_interleaved_channel;
    struct sockaddr_in udp_client;
    char session_id[32];
    char domain[128];
    char call_id[128];
    char from_tag[64];
    char to_header[512];
    char contact_uri[256];
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
    .sip_fd = -1,
    .talkback_fd = -1,
    .video_interleaved_channel = 2,
    .audio_interleaved_channel = 0,
};

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

static bool run_flexisip_script(const char *action, const char *bind_ip) {
    pid_t pid = fork();
    if (pid < 0) {
        return false;
    }
    if (pid == 0) {
        if (bind_ip != NULL) {
            execl(FLEXISIP_INIT_SCRIPT, "flexisipsh", action, bind_ip, (char *)NULL);
        } else {
            execl(FLEXISIP_INIT_SCRIPT, "flexisipsh", action, (char *)NULL);
        }
        _exit(127);
    }

    int status = 0;
    if (waitpid(pid, &status, 0) < 0) {
        return false;
    }
    return WIFEXITED(status) && WEXITSTATUS(status) == 0;
}

static bool ensure_local_sip_proxy(media_bridge_t *bridge) {
    int fd = connect_local_tcp(SIP_PORT);
    if (fd >= 0) {
        close(fd);
        return true;
    }

    if (!run_flexisip_script("start", "127.0.0.1")) {
        return false;
    }

    for (int attempt = 0; attempt < 45; attempt++) {
        fd = connect_local_tcp(SIP_PORT);
        if (fd >= 0) {
            close(fd);
            pthread_mutex_lock(&bridge->mutex);
            bridge->sip_proxy_started_by_agent = true;
            pthread_mutex_unlock(&bridge->mutex);
            struct timespec ready_delay = {2, 0};
            (void)nanosleep(&ready_delay, NULL);
            return true;
        }
        struct timespec delay = {0, 100000000L};
        (void)nanosleep(&delay, NULL);
    }

    (void)run_flexisip_script("stop", NULL);
    return false;
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
    const char *domain,
    const char *to_header,
    const char *from_tag,
    const char *call_id,
    const char *contact_uri,
    int cseq
) {
    if (fd < 0 || domain[0] == '\0' || to_header[0] == '\0' || from_tag[0] == '\0' || call_id[0] == '\0') {
        return;
    }
    const char *request_uri = (contact_uri != NULL && contact_uri[0] != '\0') ? contact_uri : "sip:c300x@127.0.0.1";
    char request[1024];
    snprintf(
        request,
        sizeof(request),
        "ACK %s SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:5060;branch=z9hG4bKack%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: %s\r\n"
        "From: <sip:webrtc@%s>;tag=%s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: %d ACK\r\n"
        "Content-Length: 0\r\n\r\n",
        request_uri,
        (long)time(NULL),
        to_header,
        domain,
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
        char domain[128];
        char call_id[128];
        char from_tag[64];
        char to_header[512];
        char contact_uri[256];
        int invite_cseq;

        pthread_mutex_lock(&bridge->mutex);
        fd = bridge->sip_fd;
        stop = bridge->sip_stop;
        snprintf(domain, sizeof(domain), "%s", bridge->domain);
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
            send_sip_ack(fd, domain, to_header, from_tag, call_id, contact_uri, invite_cseq);
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

static bool send_sip_setup(media_bridge_t *bridge) {
    char domain[128];
    if (!read_sip_domain(domain, sizeof(domain))) {
        return false;
    }

    if (!ensure_local_sip_proxy(bridge)) {
        return false;
    }
    int fd = -1;
    char call_id[128];
    char from_tag[64];
    char request[4096];
    char response[SIP_BUFFER_SIZE];
    char sdp[1024];
    snprintf(
        sdp,
        sizeof(sdp),
        "v=0\r\n"
        "o=webrtc 3747 461 IN IP4 127.0.0.1\r\n"
        "s=C300XAgent\r\n"
        "c=IN IP4 127.0.0.1\r\n"
        "t=0 0\r\n"
        "a=DEVADDR:%d\r\n"
        "m=audio 65000 RTP/SAVP 110\r\n"
        "a=rtpmap:110 speex/8000\r\n"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:dummykey\r\n"
        "m=video 65002 RTP/SAVP 96\r\n"
        "a=rtpmap:96 H264/90000\r\n"
        "a=fmtp:96 profile-level-id=42801F\r\n"
        "a=crypto:1 AES_CM_128_HMAC_SHA1_80 inline:dummykey\r\n"
        "a=recvonly\r\n",
        doorbell_devaddr(bridge->config)
    );

    int status = 0;
    for (int attempt = 0; attempt < 45; attempt++) {
        fd = connect_local_tcp(SIP_PORT);
        if (fd < 0) {
            goto retry_sip_setup;
        }

        long unique_id = ((long)time(NULL) ^ (long)getpid() ^ (long)attempt);
        snprintf(call_id, sizeof(call_id), "c300x%ld@127.0.0.1", unique_id);
        snprintf(from_tag, sizeof(from_tag), "agent%ld", unique_id);
        snprintf(
            request,
            sizeof(request),
            "REGISTER sip:%s SIP/2.0\r\n"
            "Via: SIP/2.0/TCP 127.0.0.1:5060;branch=z9hG4bKreg%ld;rport\r\n"
            "Max-Forwards: 70\r\n"
            "To: <sip:webrtc@%s>\r\n"
            "From: <sip:webrtc@%s>;tag=%s\r\n"
            "Call-ID: %s\r\n"
            "CSeq: 20 REGISTER\r\n"
            "Supported: replaces, outbound, gruu\r\n"
            "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE, SUBSCRIBE, INFO, UPDATE\r\n"
            "Contact: <sip:webrtc@127.0.0.1;transport=TCP>;expires=300;+sip.instance=\"<urn:uuid:19609c0e-f27b-7595-e9c8269557c4240b>\"\r\n"
            "Expires: 300\r\n"
            "Content-Length: 0\r\n\r\n",
            domain,
            unique_id,
            domain,
            domain,
            from_tag,
            call_id
        );
        if (send_all(fd, request, strlen(request)) <= 0 || read_message(fd, response, sizeof(response), 3) < 0) {
            goto retry_sip_setup;
        }
        if (sip_status_code(response) < 300) {
            snprintf(
                request,
                sizeof(request),
                "INVITE sip:c300x@%s SIP/2.0\r\n"
                "Via: SIP/2.0/TCP 127.0.0.1:5060;branch=z9hG4bKinv%ld;rport\r\n"
                "Max-Forwards: 70\r\n"
                "To: <sip:c300x@%s>\r\n"
                "From: <sip:webrtc@%s>;tag=%s\r\n"
                "Call-ID: %s\r\n"
                "CSeq: 21 INVITE\r\n"
                "Supported: replaces, outbound, gruu\r\n"
                "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, NOTIFY, MESSAGE, SUBSCRIBE, INFO, UPDATE\r\n"
                "Contact: <sip:webrtc@127.0.0.1;transport=TCP>\r\n"
                "Content-Type: application/sdp\r\n"
                "Content-Length: %zu\r\n\r\n%s",
                domain,
                unique_id,
                domain,
                domain,
                from_tag,
                call_id,
                strlen(sdp),
                sdp
            );
            if (send_all(fd, request, strlen(request)) <= 0) {
                goto retry_sip_setup;
            }
            status = 0;
            for (int i = 0; i < 8; i++) {
                if (read_message(fd, response, sizeof(response), 5) < 0) {
                    break;
                }
                status = sip_status_code(response);
                if (status >= 200) {
                    break;
                }
            }
            if (status >= 200 && status < 300) {
                break;
            }
        }

retry_sip_setup:
        if (fd >= 0 && (status < 200 || status >= 300)) {
            close(fd);
            fd = -1;
        }
        if (attempt + 1 < 45) {
            struct timespec delay = {2, 0};
            (void)nanosleep(&delay, NULL);
        }
    }
    if (fd < 0 || status < 200 || status >= 300) {
        if (fd >= 0) {
            close(fd);
        }
        return false;
    }

    char to_header[512];
    char contact_header[512];
    char contact_uri[256];
    header_value(response, "To:", to_header, sizeof(to_header));
    if (to_header[0] == '\0') {
        snprintf(to_header, sizeof(to_header), "<sip:c300x@%s>", domain);
    }
    header_value(response, "Contact:", contact_header, sizeof(contact_header));
    sip_uri_from_header(contact_header, contact_uri, sizeof(contact_uri));
    if (contact_uri[0] == '\0') {
        snprintf(contact_uri, sizeof(contact_uri), "sip:c300x@%s", domain);
    }

    send_sip_ack(fd, domain, to_header, from_tag, call_id, contact_uri, 21);

    pthread_mutex_lock(&bridge->mutex);
    bridge->sip_fd = fd;
    bridge->sip_stop = false;
    snprintf(bridge->domain, sizeof(bridge->domain), "%s", domain);
    snprintf(bridge->call_id, sizeof(bridge->call_id), "%s", call_id);
    snprintf(bridge->from_tag, sizeof(bridge->from_tag), "%s", from_tag);
    snprintf(bridge->to_header, sizeof(bridge->to_header), "%s", to_header);
    snprintf(bridge->contact_uri, sizeof(bridge->contact_uri), "%s", contact_uri);
    bridge->invite_cseq = 21;
    bridge->sip_monitor_started = pthread_create(&bridge->sip_thread, NULL, sip_monitor_thread, bridge) == 0;
    bool monitor_started = bridge->sip_monitor_started;
    pthread_mutex_unlock(&bridge->mutex);
    return monitor_started;
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
    bool started = false;
    for (int attempt = 0; attempt < 2 && !started; attempt++) {
        int attempt_quality = attempt == 0 ? quality : (quality == 0 ? 1 : 0);
        snprintf(
            command,
            sizeof(command),
            "*7*300#127#0#0#1#%d#%d*##",
            video_rtp_port(bridge->config),
            attempt_quality
        );
        started = send_bt_av_media_command(command, reply, sizeof(reply));
    }
    if (!started) {
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
    const char *domain,
    const char *to_header,
    const char *from_tag,
    const char *call_id,
    const char *contact_uri
) {
    if (fd < 0 || domain[0] == '\0' || to_header[0] == '\0' || from_tag[0] == '\0' || call_id[0] == '\0') {
        return;
    }
    const char *request_uri = (contact_uri != NULL && contact_uri[0] != '\0') ? contact_uri : "sip:c300x@127.0.0.1";
    char request[1024];
    snprintf(
        request,
        sizeof(request),
        "BYE %s SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:5060;branch=z9hG4bKbye%ld;rport\r\n"
        "Max-Forwards: 70\r\n"
        "To: %s\r\n"
        "From: <sip:webrtc@%s>;tag=%s\r\n"
        "Call-ID: %s\r\n"
        "CSeq: 22 BYE\r\n"
        "Content-Length: 0\r\n\r\n",
        request_uri,
        (long)time(NULL),
        to_header,
        domain,
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
    bool sip_ready = false;
    bool wants_audio = false;

    pthread_mutex_lock(&bridge->mutex);
    if (bridge->media_active || bridge->media_starting) {
        pthread_mutex_unlock(&bridge->mutex);
        return true;
    }
    wants_audio = bridge->rtsp_audio_enabled;
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

    if (sip_video_call_enabled()) {
        sip_ready = send_sip_setup(bridge);
        if (!sip_ready) {
            c300x_video_bridge_set_error(bridge->video, "sip_setup_failed");
            stop_media_session(false);
            c300x_video_bridge_media_stopped(bridge->video);
            return false;
        }
    }
    if (wants_audio && sip_ready && !start_talkback_proxy(bridge)) {
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
    c300x_video_bridge_media_started(bridge->video, wants_audio);
    return true;
}

static void *start_media_session_thread(void *arg) {
    (void)start_media_session((media_bridge_t *)arg);
    return NULL;
}

static void start_media_session_async(media_bridge_t *bridge) {
    pthread_t thread;
    if (pthread_create(&thread, NULL, start_media_session_thread, bridge) == 0) {
        pthread_detach(thread);
    }
}

static void stop_media_session(bool close_client) {
    int sip_fd = -1;
    char domain[128];
    char call_id[128];
    char from_tag[64];
    char to_header[512];
    char contact_uri[256];
    bool relay_started = false;
    bool sip_monitor_started = false;
    bool talkback_started = false;
    bool send_media_stop = false;
    bool stop_sip_proxy = false;
    pthread_t sip_thread;
    pthread_t talkback_thread;

    domain[0] = '\0';
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
        && !g_bridge.talkback_started
        && g_bridge.rtp_fd < 0
        && g_bridge.audio_rtp_fd < 0
        && g_bridge.sip_fd < 0
        && g_bridge.talkback_fd < 0
        && !g_bridge.sip_proxy_started_by_agent
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
    g_bridge.talkback_stop = true;
    send_media_stop = g_bridge.media_active || g_bridge.relay_started;
    relay_started = g_bridge.relay_started;
    sip_monitor_started = g_bridge.sip_monitor_started;
    talkback_started = g_bridge.talkback_started;
    stop_sip_proxy = g_bridge.sip_proxy_started_by_agent;
    sip_thread = g_bridge.sip_thread;
    talkback_thread = g_bridge.talkback_thread;
    g_bridge.relay_started = false;
    g_bridge.talkback_started = false;
    g_bridge.sip_proxy_started_by_agent = false;
    sip_fd = g_bridge.sip_fd;
    snprintf(domain, sizeof(domain), "%s", g_bridge.domain);
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

    if (send_media_stop) {
        send_bt_av_media_stop();
    }
    if (sip_fd >= 0) {
        send_sip_bye(sip_fd, domain, to_header, from_tag, call_id, contact_uri);
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
    if (stop_sip_proxy) {
        (void)run_flexisip_script("stop", NULL);
    }

    pthread_mutex_lock(&g_bridge.mutex);
    g_bridge.media_active = false;
    g_bridge.media_starting = false;
    g_bridge.sip_stop = false;
    g_bridge.talkback_stop = false;
    g_bridge.sip_monitor_started = false;
    if (g_bridge.rtp_fd >= 0) {
        close(g_bridge.rtp_fd);
        g_bridge.rtp_fd = -1;
    }
    if (g_bridge.audio_rtp_fd >= 0) {
        close(g_bridge.audio_rtp_fd);
        g_bridge.audio_rtp_fd = -1;
    }
    if (g_bridge.talkback_fd >= 0) {
        close(g_bridge.talkback_fd);
        g_bridge.talkback_fd = -1;
    }
    g_bridge.domain[0] = '\0';
    g_bridge.call_id[0] = '\0';
    g_bridge.from_tag[0] = '\0';
    g_bridge.to_header[0] = '\0';
    g_bridge.contact_uri[0] = '\0';
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
        open_fds += g_bridge.talkback_fd >= 0 ? 1 : 0;
        open_fds += g_bridge.sip_fd >= 0 ? 1 : 0;
        active_threads += g_bridge.running ? 1 : 0;
        active_threads += g_bridge.relay_started ? 1 : 0;
        active_threads += g_bridge.sip_monitor_started ? 1 : 0;
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
            start_media_session_async(&g_bridge);
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

    close(server_fd);
    pthread_mutex_lock(&bridge->mutex);
    bridge->listen_fd = -1;
    pthread_mutex_unlock(&bridge->mutex);
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
