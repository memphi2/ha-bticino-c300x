#include "self_test.h"

#include "device_user.h"
#include "device_routing.h"
#include "string_util.h"

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

#define C300X_SELF_TEST_API_VERSION "1.1"
#define C300X_SELF_TEST_FIREWALL_BEGIN "# c300x-native-agent firewall begin"
#define C300X_SELF_TEST_FIREWALL_END "# c300x-native-agent firewall end"
#define C300X_SELF_TEST_IPV6_FIREWALL_BEGIN "# c300x-native-agent ipv6 firewall begin"
#define C300X_SELF_TEST_IPV6_FIREWALL_END "# c300x-native-agent ipv6 firewall end"
#define C300X_SELF_TEST_FILE_MAX 49152
#define C300X_AGENT_INIT_SCRIPT "/etc/init.d/c300x-native-agent"
#define C300X_AGENT_INIT_LINK "/etc/rc5.d/S40c300x-native-agent"

static const char *bool_json(int value)
{
    return value ? "true" : "false";
}

static const char *check_json(int value)
{
    if (value < 0) {
        return "null";
    }
    return bool_json(value);
}

static const char *firmware_family(const struct c300x_config *config)
{
    if (config == NULL || config->device_firmware[0] == '\0') {
        return "unknown";
    }
    if (strncmp(config->device_firmware, "1.7.", 4) == 0) {
        return "1.7.x";
    }
    return "unknown";
}

static const char *json_string(const char *value, char *out, size_t out_len)
{
    size_t used = 0;

    if (out_len == 0) {
        return "";
    }
    out[0] = '\0';
    if (!c300x_appendf(out, out_len, &used, "\"")) {
        return out;
    }
    if (value == NULL) {
        value = "";
    }
    for (const unsigned char *p = (const unsigned char *)value; *p != '\0'; p++) {
        if (*p == '"' || *p == '\\') {
            if (!c300x_appendf(out, out_len, &used, "\\%c", *p)) {
                return out;
            }
        } else if (*p == '\n') {
            if (!c300x_appendf(out, out_len, &used, "\\n")) {
                return out;
            }
        } else if (*p == '\r') {
            if (!c300x_appendf(out, out_len, &used, "\\r")) {
                return out;
            }
        } else if (*p == '\t') {
            if (!c300x_appendf(out, out_len, &used, "\\t")) {
                return out;
            }
        } else if (*p < 0x20) {
            if (!c300x_appendf(out, out_len, &used, "\\u%04x", *p)) {
                return out;
            }
        } else if (!c300x_appendf(out, out_len, &used, "%c", *p)) {
            return out;
        }
    }
    (void)c300x_appendf(out, out_len, &used, "\"");
    return out;
}

static int read_text_file(const char *path, char *buffer, size_t buffer_len, int *exists)
{
    FILE *file;
    size_t read_len;

    if (exists != NULL) {
        *exists = 0;
    }
    if (buffer_len == 0) {
        return 0;
    }
    buffer[0] = '\0';
    file = fopen(path, "rb");
    if (file == NULL) {
        return errno == ENOENT;
    }
    if (exists != NULL) {
        *exists = 1;
    }
    read_len = fread(buffer, 1, buffer_len - 1, file);
    if (ferror(file)) {
        fclose(file);
        return 0;
    }
    buffer[read_len] = '\0';
    if (read_len == buffer_len - 1 && fgetc(file) != EOF) {
        fclose(file);
        return 0;
    }
    fclose(file);
    return 1;
}

static int agent_init_link_matches(void)
{
    char current[C300X_MAX_PATH_LEN];
    char resolved[PATH_MAX];
    ssize_t len = readlink(C300X_AGENT_INIT_LINK, current, sizeof(current) - 1);

    if (len < 0) {
        return 0;
    }
    current[len] = '\0';
    if (strcmp(current, C300X_AGENT_INIT_SCRIPT) == 0) {
        return 1;
    }
    if (realpath(C300X_AGENT_INIT_LINK, resolved) == NULL) {
        return 0;
    }
    return strcmp(resolved, C300X_AGENT_INIT_SCRIPT) == 0;
}

static const char *firewall_state_for(
    const char *content,
    int exists,
    const char *begin_marker,
    const char *end_marker
)
{
    const char *begin;
    const char *end;

    if (!exists) {
        return "missing";
    }
    begin = strstr(content, begin_marker);
    if (begin == NULL) {
        return "original";
    }
    end = strstr(begin, end_marker);
    if (end == NULL || strstr(content, end_marker) != end) {
        return "partial";
    }
    return "patched";
}

static const char *read_firewall_state(
    const char *path,
    const char *begin_marker,
    const char *end_marker,
    char *state,
    size_t state_len,
    int *exists
)
{
    char *content = calloc(1, C300X_SELF_TEST_FILE_MAX);
    const char *result = "read_failed";

    if (content == NULL) {
        c300x_copy_string(state, state_len, "out_of_memory");
        return state;
    }
    if (read_text_file(path, content, C300X_SELF_TEST_FILE_MAX, exists)) {
        result = firewall_state_for(content, exists != NULL ? *exists : 0, begin_marker, end_marker);
    }
    c300x_copy_string(state, state_len, result);
    free(content);
    return state;
}

int c300x_self_test_json(
    const struct c300x_config *config,
    const struct c300x_video_status *video_status,
    int agent_init_script_present,
    int agent_init_link_ok,
    char *out,
    size_t out_len
)
{
    char firmware_json[64];
    char ipv4_state[32] = "unknown";
    char ipv6_state[32] = "unknown";
    char user_error_json[C300X_DEVICE_USER_ERROR_LEN * 6 + 3];
    char routing_state_json[96];
    char routing_error_json[C300X_DEVICE_ROUTING_ERROR_LEN * 6 + 3];
    struct c300x_device_user_status user_status;
    struct c300x_device_routing_status routing_status;
    int ipv4_exists = 0;
    int ipv6_exists = 0;
    int capabilities_ok = config != NULL;
    int firewall_ok = 1;
    int ipv4_firewall_ok = 1;
    int ipv6_firewall_ok = 1;
    int rtsp_ok = 1;
    int talkback_ok = 1;
    int user_ok = 1;
    int routing_read_ok = 0;
    int device_routing_ok = 1;
    int startup_ok = agent_init_script_present && agent_init_link_ok;
    int video_enabled = config != NULL && config->video_enabled;
    const char *firewall_reason = "media_disabled";
    const char *rtsp_reason = "media_disabled";
    const char *talkback_reason = "media_disabled";
    const char *user_reason = "media_disabled";
    const char *device_routing_reason = "not_required_without_homeassistant_user";
    const char *startup_reason = "startup_link_ok";
    size_t used = 0;

    memset(&user_status, 0, sizeof(user_status));
    memset(&routing_status, 0, sizeof(routing_status));
    if (config == NULL || out == NULL || out_len == 0) {
        return 0;
    }

    read_firewall_state(
        config->maintenance_firewall_path,
        C300X_SELF_TEST_FIREWALL_BEGIN,
        C300X_SELF_TEST_FIREWALL_END,
        ipv4_state,
        sizeof(ipv4_state),
        &ipv4_exists
    );
    if (config->maintenance_ipv6_firewall_enabled) {
        read_firewall_state(
            config->maintenance_ipv6_firewall_path,
            C300X_SELF_TEST_IPV6_FIREWALL_BEGIN,
            C300X_SELF_TEST_IPV6_FIREWALL_END,
            ipv6_state,
            sizeof(ipv6_state),
            &ipv6_exists
        );
    } else {
        c300x_copy_string(ipv6_state, sizeof(ipv6_state), "disabled");
    }

    if (video_enabled) {
        ipv4_firewall_ok = strcmp(ipv4_state, "patched") == 0;
        ipv6_firewall_ok = !config->maintenance_ipv6_firewall_enabled
            || strcmp(ipv6_state, "patched") == 0;
        firewall_ok = ipv4_firewall_ok;
        if (!ipv4_firewall_ok) {
            firewall_reason = "ipv4_media_ports_missing";
        } else if (!ipv6_firewall_ok) {
            firewall_reason = "media_ports_open_ipv6_optional_missing";
        } else {
            firewall_reason = "media_ports_open";
        }

        if (video_status == NULL) {
            rtsp_ok = 0;
            rtsp_reason = "video_runtime_unavailable";
        } else if (!video_status->enabled || !video_status->running) {
            rtsp_ok = 0;
            rtsp_reason = "rtsp_server_not_running";
        } else if (config->video_rtsp_port == 0 || config->video_rtsp_path[0] == '\0') {
            rtsp_ok = 0;
            rtsp_reason = "rtsp_config_missing";
        } else {
            rtsp_reason = "rtsp_ready";
        }

        talkback_ok = firewall_ok && C300X_TALKBACK_RTP_PORT > 0;
        talkback_reason = talkback_ok ? "talkback_rtp_ready" : "talkback_rtp_firewall_missing";

        if (!c300x_device_user_read_status(&user_status)) {
            user_ok = 0;
            device_routing_ok = 0;
            user_reason = "device_user_status_unavailable";
            device_routing_reason = "not_checked_device_user_status_unavailable";
        } else if (!user_status.media_identity_available) {
            user_ok = 0;
            user_reason = "media_identity_missing";
        } else if (user_status.homeassistant_user_present && !user_status.routes_consistent) {
            user_ok = 0;
            user_reason = "homeassistant_routes_inconsistent";
        } else if (user_status.homeassistant_user_present) {
            user_reason = "homeassistant_user_ok";
        } else {
            user_reason = "homeassistant_user_missing";
        }

        if (user_status.status_available) {
            routing_read_ok = c300x_device_routing_read_status(&routing_status);
        }
        if (user_status.status_available && user_status.homeassistant_user_present) {
            device_routing_ok = routing_read_ok
                && routing_status.patched;
            if (!routing_read_ok) {
                device_routing_reason = "device_routing_status_failed";
            } else if (!routing_status.patched) {
                device_routing_reason = "device_routing_missing";
            } else {
                device_routing_reason = "device_routing_ok";
            }
        }
    }

    if (!agent_init_script_present) {
        startup_reason = "agent_init_script_missing";
    } else if (!agent_init_link_ok) {
        startup_reason = "startup_link_missing";
    }

    json_string(firmware_family(config), firmware_json, sizeof(firmware_json));
    json_string(user_status.error, user_error_json, sizeof(user_error_json));
    json_string(routing_status.state, routing_state_json, sizeof(routing_state_json));
    json_string(routing_status.error, routing_error_json, sizeof(routing_error_json));

    out[0] = '\0';
    return c300x_appendf(
        out,
        out_len,
        &used,
        "{\"api_version\":\"%s\",\"agent_version\":\"%s\",\"firmware_family\":%s,"
        "\"ok\":%s,\"checks\":{"
        "\"capabilities\":{\"ok\":%s,\"reason\":\"%s\",\"api_version\":\"%s\",\"agent_version\":\"%s\"},"
        "\"firewall\":{\"ok\":%s,\"reason\":\"%s\",\"ipv4_state\":\"%s\",\"ipv4_exists\":%s,"
        "\"ipv6_state\":\"%s\",\"ipv6_exists\":%s,\"ipv6_enabled\":%s,\"rtsp_port\":%u,\"talkback_rtp_port\":%u},"
        "\"rtsp\":{\"ok\":%s,\"reason\":\"%s\",\"enabled\":%s,\"running\":%s,\"bridge_running\":%s,"
        "\"clients\":%d,\"max_clients\":%d},"
        "\"talkback_rtp\":{\"ok\":%s,\"reason\":\"%s\",\"port\":%u},"
        "\"homeassistant_user\":{\"ok\":%s,\"reason\":\"%s\",\"supported\":%s,\"media_identity_available\":%s,"
        "\"homeassistant_user_present\":%s,\"routes_consistent\":%s,\"error\":%s},"
        "\"device_routing\":{\"ok\":%s,\"reason\":\"%s\",\"routing_supported\":%s,\"routing_applied\":%s,"
        "\"routing_state\":%s,\"routing_error\":%s},"
        "\"startup\":{\"ok\":%s,\"reason\":\"%s\",\"agent_init_script_present\":%s,\"agent_init_link_ok\":%s}"
        "}}\n",
        C300X_SELF_TEST_API_VERSION,
        C300X_NATIVE_AGENT_VERSION,
        firmware_json,
        bool_json(
            capabilities_ok
            && firewall_ok
            && rtsp_ok
            && talkback_ok
            && user_ok != 0
            && device_routing_ok != 0
            && startup_ok
        ),
        bool_json(capabilities_ok),
        capabilities_ok ? "ok" : "config_missing",
        C300X_SELF_TEST_API_VERSION,
        C300X_NATIVE_AGENT_VERSION,
        bool_json(firewall_ok),
        firewall_reason,
        ipv4_state,
        bool_json(ipv4_exists),
        ipv6_state,
        bool_json(ipv6_exists),
        bool_json(config->maintenance_ipv6_firewall_enabled),
        config->video_rtsp_port,
        C300X_TALKBACK_RTP_PORT,
        bool_json(rtsp_ok),
        rtsp_reason,
        bool_json(video_status != NULL && video_status->enabled),
        bool_json(video_status != NULL && video_status->running),
        bool_json(video_status != NULL && video_status->bridge_running),
        video_status != NULL ? video_status->clients : 0,
        video_status != NULL ? video_status->max_clients : 0,
        bool_json(talkback_ok),
        talkback_reason,
        C300X_TALKBACK_RTP_PORT,
        check_json(user_ok),
        user_reason,
        bool_json(user_status.supported),
        bool_json(user_status.media_identity_available),
        bool_json(user_status.homeassistant_user_present),
        bool_json(user_status.routes_consistent),
        user_error_json,
        check_json(device_routing_ok),
        device_routing_reason,
        bool_json(routing_status.supported),
        bool_json(routing_status.patched),
        routing_state_json,
        routing_error_json,
        bool_json(startup_ok),
        startup_reason,
        bool_json(agent_init_script_present),
        bool_json(agent_init_link_ok)
    );
}

static void write_all(int fd, const char *data, size_t len)
{
    while (len > 0) {
        ssize_t written = write(fd, data, len);
        if (written < 0 && errno == EINTR) {
            continue;
        }
        if (written <= 0) {
            return;
        }
        data += written;
        len -= (size_t)written;
    }
}

static void send_json_response(int client_fd, int status, const char *reason, const char *body)
{
    char header[256];
    size_t body_len = strlen(body);
    int header_len = snprintf(
        header,
        sizeof(header),
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: application/json\r\n"
        "Cache-Control: no-store\r\n"
        "Content-Length: %zu\r\n"
        "Connection: close\r\n"
        "\r\n",
        status,
        reason,
        body_len
    );

    if (header_len > 0 && header_len < (int)sizeof(header)) {
        write_all(client_fd, header, (size_t)header_len);
    }
    write_all(client_fd, body, body_len);
}

void c300x_self_test_send_response(
    int client_fd,
    const struct c300x_config *config,
    struct c300x_video *video
)
{
    struct c300x_video_status video_status;
    struct c300x_video_status *video_status_ptr = NULL;
    char body[8192];

    memset(&video_status, 0, sizeof(video_status));
    if (video != NULL) {
        c300x_video_status(video, &video_status);
        video_status_ptr = &video_status;
    }
    if (!c300x_self_test_json(
        config,
        video_status_ptr,
        access(C300X_AGENT_INIT_SCRIPT, X_OK) == 0,
        agent_init_link_matches(),
        body,
        sizeof(body)
    )) {
        send_json_response(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        return;
    }
    send_json_response(client_fd, 200, "OK", body);
}
