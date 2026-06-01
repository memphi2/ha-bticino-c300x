#include "c300x_agent.h"
#include "mdns.h"
#include "mqtt_bridge.h"
#include "sha256.h"
#include "video_rtsp.h"

#include <arpa/inet.h>
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <limits.h>
#include <netdb.h>
#include <net/if.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <strings.h>
#include <sys/inotify.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define REQUEST_BUFFER_SIZE 8192
#define C300X_MAX_SUBSCRIPTIONS 4
#define C300X_MAX_SUBSCRIPTION_EVENTS 16
#define C300X_MAX_RECENT_EVENTS 16
#define C300X_RECENT_EVENT_LEN 2048
#define C300X_MAX_URL_LEN 512
#define C300X_EVENT_TOKEN_HEADER "X-Bticino-C300X-Event-Token"
#define C300X_DASHBOARD_DOMAIN "c300x"
#define C300X_DASHBOARD_STAIR_LIGHT_ENTITY "stair_light"
#define C300X_MAX_VOICEMAIL_WATCHES (C300X_MAX_VOICEMAIL_MESSAGES + 1)
#define C300X_MESSAGE_WATCH_MASK (IN_CREATE | IN_DELETE | IN_MODIFY | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_ATTRIB | IN_DELETE_SELF | IN_MOVE_SELF)
#define C300X_MAX_VOICEMAIL_ID_LEN 65
#define C300X_MAX_VOICEMAIL_DATE_LEN 64
#define C300X_MAX_VOICEMAIL_REASON_LEN 48
#define C300X_MAX_MEMO_TEXT_LEN 512
#define C300X_MAX_MEMO_TEXT_JSON_LEN ((C300X_MAX_MEMO_TEXT_LEN * 6) + 1)
#define C300X_MAX_PATH_JSON_LEN ((C300X_MAX_PATH_LEN * 6) + 1)
#define C300X_JSON_QUOTED_LEN(value_len) (((value_len) * 6) + 3)
#define C300X_TOKEN_FINGERPRINT_LEN 32
#define C300X_ANSWERING_DIRECTORY_VIDEO_MESSAGE 0
#define C300X_ANSWERING_DIRECTORY_VOICE_MEMO 2
#define C300X_ANSWERING_DIRECTORY_TEXT_MEMO 3
#define C300X_UI_LISTEN_HOST "127.0.0.1"
#define C300X_FIREWALL_BEGIN "# c300x-native-agent firewall begin"
#define C300X_FIREWALL_END "# c300x-native-agent firewall end"
#define C300X_IPV6_FIREWALL_BEGIN "# c300x-native-agent ipv6 firewall begin"
#define C300X_IPV6_FIREWALL_END "# c300x-native-agent ipv6 firewall end"
#define C300X_FIREWALL_BUFFER_SIZE 49152
#define C300X_NETWORK_ONLINE_RECHECK_SECONDS 5
#define C300X_NETWORK_OFFLINE_RECHECK_SECONDS 30
#define C300X_HOME_ASSISTANT_CONNECTED_SECONDS 300
#define C300X_AGENT_UPDATE_STAGE ".update"
#define C300X_AGENT_BUNDLE_MANIFEST "bundle.json"
#define C300X_AGENT_BUNDLE_HASH_LEN 96
#define C300X_AGENT_INIT_SCRIPT "/etc/init.d/c300x-native-agent"
#define C300X_AGENT_INIT_LINK "/etc/rc5.d/S40c300x-native-agent"
#define C300X_LEGACY_MQTT_DIR "/etc/tcpdump2mqtt"
#define C300X_LEGACY_MQTT_CONFIG "/etc/tcpdump2mqtt/TcpDump2Mqtt.conf"
#define C300X_LEGACY_MQTT_SCRIPT "/etc/tcpdump2mqtt/TcpDump2Mqtt.sh"
#define C300X_LEGACY_MQTT_INIT_LINK "/etc/rc5.d/S99TcpDump2Mqtt"
#define C300X_LEGACY_MQTT_INIT_TARGET "../tcpdump2mqtt/TcpDump2Mqtt.sh"
#define C300X_LEGACY_MQTT_BACKUP_DIR "/home/bticino/cfg/extra/c300x-device-file-backups/legacy-mqtt"
#define C300X_LEGACY_MQTT_BACKUP_MARKER "/home/bticino/cfg/extra/c300x-device-file-backups/legacy-mqtt/.complete"
#define C300X_LARGE_RESPONSE_SIZE 32768

enum listener_kind {
    LISTENER_API = 1,
    LISTENER_UI = 2
};

struct listener {
    int fd;
    enum listener_kind kind;
};

struct request {
    char method[8];
    char path[256];
    char query[256];
    char headers[REQUEST_BUFFER_SIZE];
    char body[REQUEST_BUFFER_SIZE];
    size_t body_len;
};

struct request_workspace {
    char buffer[REQUEST_BUFFER_SIZE];
    struct request request;
};

struct agent_update_change_summary {
    int changed_files;
    int runtime_changed;
    int qml_patch_changed;
    int script_changed;
    int firewall_patch_changed;
    int ipv6_firewall_patch_changed;
    int config_schema_changed;
    int manifest_changed;
};

struct subscription {
    char id[48];
    char callback_url[C300X_MAX_URL_LEN];
    char token[C300X_MAX_TOKEN_LEN];
    char events[C300X_MAX_SUBSCRIPTION_EVENTS][64];
    int event_count;
    char last_event_type[64];
    char last_delivered_at[40];
    int last_ok;
};

struct voicemail_message {
    char id[C300X_MAX_VOICEMAIL_ID_LEN];
    char kind[16];
    int read;
    char date[C300X_MAX_VOICEMAIL_DATE_LEN];
    long long unix_time;
    char iso_time[40];
    int has_thumbnail;
    int has_video;
    char video_mime_type[32];
    long long video_size;
    int has_text;
    int has_audio;
    char audio_mime_type[32];
    long long audio_size;
    int text_truncated;
    long long timestamp;
    char dir_path[C300X_MAX_PATH_LEN];
    char text[C300X_MAX_MEMO_TEXT_LEN + 1];
};

struct voicemail_snapshot {
    int available;
    char reason[C300X_MAX_VOICEMAIL_REASON_LEN];
    int total;
    int unread;
    int read;
    int text_total;
    int voice_total;
    char newest_at[C300X_MAX_VOICEMAIL_DATE_LEN];
    int message_count;
    struct voicemail_message messages[C300X_MAX_VOICEMAIL_MESSAGES];
};

struct voicemail_watch {
    int wd;
    int is_root;
    char path[C300X_MAX_PATH_LEN];
};

struct voicemail_runtime {
    int enabled;
    int watch_enabled;
    int max_messages;
    char root[C300X_MAX_PATH_LEN];
    int inotify_fd;
    int watch_count;
    struct voicemail_watch watches[C300X_MAX_VOICEMAIL_WATCHES];
    unsigned long long last_signature;
};

struct system_metrics_sample {
    long cpu_count;
    unsigned long long cpu_total_jiffies;
    unsigned long long cpu_idle_jiffies;
    int has_cpu_jiffies;
    int has_cpu_usage;
    double cpu_usage_percent;
    double load_1m;
    double load_5m;
    double load_15m;
    double load_1m_percent;
    double load_5m_percent;
    double load_15m_percent;
    int has_memory;
    long memory_total_kb;
    long memory_available_kb;
    long memory_used_kb;
    double memory_usage_percent;
    int has_temperature;
    double temperature_c;
    char temperature_source[C300X_MAX_PATH_LEN];
};

struct agent_runtime {
    struct subscription subscriptions[C300X_MAX_SUBSCRIPTIONS];
    int subscription_count;
    int subscriptions_loaded_deduplicated;
    int home_assistant_connected_this_run;
    time_t home_assistant_last_seen_at;
    int display_bridge_registered;
    int display_bridge_disabled;
    char display_bridge_webhook_url[C300X_MAX_URL_LEN];
    char display_bridge_shared_secret[C300X_MAX_TOKEN_LEN];
    unsigned long agent_write_count;
    unsigned long subscription_store_writes;
    unsigned long loop_iterations;
    unsigned long poll_wakeups;
    unsigned long accepted_clients;
    time_t last_write_at;
    int last_poll_timeout_ms;
    int last_poll_count;
    char last_write_reason[128];
    char last_write_class[32];
    char last_wake_reason[64];
    char qml_patch_last_action[32];
    char recent_events[C300X_MAX_RECENT_EVENTS][C300X_RECENT_EVENT_LEN];
    int recent_count;
    struct c300x_video *video;
    struct voicemail_runtime voicemail;
    struct voicemail_runtime text_memos;
    struct voicemail_runtime voice_memos;
    unsigned long long memos_last_signature;
    unsigned long ui_event_revision;
    int ui_event_wait_fd;
    unsigned long ui_event_wait_since;
    time_t ui_event_wait_deadline;
    char ui_event_topic[64];
    /* Sampling uses the previous sample for CPU jiffies; dispatch thresholds
     * compare against the last sample actually delivered to Home Assistant. */
    struct system_metrics_sample system_metrics_last;
    struct system_metrics_sample system_metrics_last_dispatched;
    int system_metrics_initialized;
    int system_metrics_dispatched_initialized;
    time_t system_metrics_next_sample_at;
    time_t system_metrics_last_dispatched_at;
    int network_online;
    time_t network_checked_at;
    struct c300x_mqtt mqtt;
};

struct firewall_workspace {
    char current[C300X_FIREWALL_BUFFER_SIZE];
    char base[C300X_FIREWALL_BUFFER_SIZE];
    char original_backup[C300X_FIREWALL_BUFFER_SIZE];
    char desired[C300X_FIREWALL_BUFFER_SIZE];
};

static void send_json(int client_fd, int status, const char *reason, const char *body);
static void send_file_response(
    int client_fd,
    const char *path,
    const char *content_type,
    const char *cache_control
);
static void request_path_and_query(const char *line_path, char *path, size_t path_len, char *query, size_t query_len);
static int query_param_value(const char *query, const char *key, char *out, size_t out_len);
static int validate_action_id(const char *value);
static int validate_alarm_command(const char *value);
static int validate_alarm_code(const char *value);
static int validate_event_name(const char *value);
static int config_admin_authorized(const struct c300x_config *config, const struct request *request);
static int auth_config_read_authorized(const struct c300x_config *config, const struct request *request);
static int maintenance_authorized(const struct c300x_config *config, const struct request *request);
static int maintenance_auth_available(const struct c300x_config *config);
static int auth_config_requires_restart(
    const struct c300x_config *current,
    const struct c300x_config *updated
);
static void handle_ui_homeassistant(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static void handle_ui_action(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static void handle_ui_stair_light(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static void handle_ui_alarm_command(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static int forward_to_homeassistant(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const char *body,
    char *response,
    size_t response_len
);
static void mark_home_assistant_callback_seen(struct agent_runtime *runtime, time_t now);
static void handle_display_bridge_post(
    int client_fd,
    struct agent_runtime *runtime,
    const struct c300x_config *config,
    const struct request *request
);
static void handle_display_bridge_status(
    int client_fd,
    const struct c300x_config *config,
    const struct agent_runtime *runtime
);
static void handle_display_bridge_event_post(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static void handle_diagnostics_get(int client_fd, const struct agent_runtime *runtime);
static void handle_setup_page(int client_fd);
static void handle_auth_config_get(int client_fd, const struct c300x_config *config);
static void handle_auth_config_post(
    int client_fd,
    struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static void handle_mqtt_status(
    int client_fd,
    const struct c300x_config *config,
    const struct agent_runtime *runtime
);
static void handle_mqtt_post(
    int client_fd,
    struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static int parse_http_url(const char *url, char *host, size_t host_len, char *port, size_t port_len, char *path, size_t path_len);
static void http_host_header_value(const char *host, const char *port, char *out, size_t out_len);
static void set_socket_timeout(int fd, int timeout_ms);
static void set_fd_nonblocking(int fd);
static void set_fd_cloexec(int fd);
static void dispatch_event(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const char *event_type,
    const char *data_json,
    int ttl_seconds
);
static int has_matching_subscription(
    const struct agent_runtime *runtime,
    const char *event_type
);
static int system_metrics_watch_active(
    const struct c300x_config *config,
    const struct agent_runtime *runtime
);
static const char *json_string(const char *value, char *out, size_t out_len);
static void json_string_field(const char *body, const char *field, char *out, size_t out_len);
static int json_bool_field(const char *body, const char *field, int *out);
static int json_int_field(const char *body, const char *field, int *out);
static int constant_time_equal(const char *left, size_t left_len, const char *right);
static int metric_changed_percent(double previous, double current, int threshold_percent);
static int metric_changed_points(double previous, double current, int threshold_points);
static int event_requests_metrics_refresh(const char *event_type);
static int runtime_network_online(struct agent_runtime *runtime, time_t now);
static int local_network_online(void);
static int timeout_until_ms(time_t now, time_t due);
static int min_timeout_ms(int current, int candidate);
static void system_metrics_dispatch_now(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    time_t now
);
static int read_system_metrics_sample(
    struct system_metrics_sample *sample,
    const struct system_metrics_sample *previous
);
static void system_metrics_mark_dispatched(
    struct agent_runtime *runtime,
    const struct system_metrics_sample *sample,
    time_t now
);
static int system_metrics_json(
    const struct system_metrics_sample *sample,
    int include_ok,
    char *body,
    size_t body_len
);
static void handle_answering_messages_get(int client_fd, struct agent_runtime *runtime);
static void handle_answering_message_video_get(
    int client_fd,
    const struct agent_runtime *runtime,
    const char *message_id
);
static void handle_answering_message_delete(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static void handle_memos_get(int client_fd, const struct agent_runtime *runtime);
static void handle_memos_delete(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static void handle_memo_audio_get(
    int client_fd,
    const struct agent_runtime *runtime,
    const char *memo_entry_name
);
static int find_memo_audio(
    const struct voicemail_runtime *memos,
    const char *entry_name,
    char *path,
    size_t path_len,
    const char **content_type,
    long long *size
);
static void handle_qml_patch_status(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
);
static void handle_qml_patch_action(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request,
    const char *action,
    const char *confirmation
);
static void handle_firewall_status(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
);
static void handle_firewall_action(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request,
    const char *action,
    const char *confirmation
);
static void handle_gui_reload(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
);
static void handle_remove_agent(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
);
static void handle_agent_update_status(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
);
static void handle_agent_update_prepare(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static void handle_agent_update_file(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static void handle_agent_update_apply(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static void handle_config_normalize(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
);
static int apply_agent_update_init_script(
    const struct c300x_config *config,
    const char *stage_path,
    int *changed
);
static int client_is_loopback(int client_fd);
static int path_parent_inplace(char *path);
static int read_bounded_text_file(
    const char *path,
    char *out,
    size_t out_len,
    int *truncated
);
static int confirm_matches(const struct request *request, const char *expected);

static void request_path_and_query(
    const char *line_path,
    char *path,
    size_t path_len,
    char *query,
    size_t query_len
)
{
    char copied_path[256];
    const char *normalized_path = line_path ? line_path : "";
    const char *query_start;

    snprintf(copied_path, sizeof(copied_path), "%s", normalized_path);

    query_start = strchr(copied_path, '?');
    if (path_len > 0) {
        path[0] = '\0';
    }
    if (query_len > 0) {
        query[0] = '\0';
    }
    if (query_start == NULL) {
        size_t path_size = strlen(copied_path);
        if (path_size >= path_len) {
            path_size = path_len > 0 ? path_len - 1 : 0;
        }
        if (path_len > 0) {
            memcpy(path, copied_path, path_size);
            path[path_size] = '\0';
        }
        return;
    }

    if (query_start > copied_path) {
        size_t path_size = (size_t)(query_start - copied_path);
        if (path_size >= path_len) {
            path_size = path_len > 0 ? path_len - 1 : 0;
        }
        if (path_len > 0) {
            memcpy(path, copied_path, path_size);
            path[path_size] = '\0';
        }
    } else if (path_len > 0) {
        path[0] = '/';
        path[1] = '\0';
    }
    if (query_len > 0) {
        snprintf(query, query_len, "%s", query_start + 1);
    }
}

static int hex_digit_value(char ch)
{
    if (ch >= '0' && ch <= '9') {
        return ch - '0';
    }
    if (ch >= 'a' && ch <= 'f') {
        return ch - 'a' + 10;
    }
    if (ch >= 'A' && ch <= 'F') {
        return ch - 'A' + 10;
    }
    return -1;
}

static void percent_decode_query_value(
    const char *value_start,
    const char *value_end,
    char *out,
    size_t out_len
)
{
    size_t written = 0;

    if (out_len == 0) {
        return;
    }
    while (value_start < value_end && written + 1 < out_len) {
        if (*value_start == '%' && value_start + 2 < value_end) {
            int high = hex_digit_value(value_start[1]);
            int low = hex_digit_value(value_start[2]);
            if (high >= 0 && low >= 0) {
                out[written++] = (char)((high << 4) | low);
                value_start += 3;
                continue;
            }
        }
        out[written++] = *value_start == '+' ? ' ' : *value_start;
        value_start++;
    }
    out[written] = '\0';
}

static int query_param_value(const char *query, const char *key, char *out, size_t out_len)
{
    const char *ptr;
    size_t key_len = strlen(key);
    if (out_len > 0) {
        out[0] = '\0';
    }
    if (query == NULL || key == NULL || key_len == 0 || out_len == 0) {
        return 0;
    }
    ptr = query;
    while (*ptr != '\0') {
        const char *value_start;
        const char *pair_end;

        while (*ptr == '&') {
            ptr++;
        }
        if (*ptr == '\0') {
            break;
        }
        pair_end = strchr(ptr, '&');
        if (pair_end == NULL) {
            pair_end = ptr + strlen(ptr);
        }
        if (strncmp(ptr, key, key_len) == 0 && ptr[key_len] == '=') {
            value_start = ptr + key_len + 1;
            percent_decode_query_value(value_start, pair_end, out, out_len);
            return 1;
        }
        ptr = pair_end;
        if (*ptr == '&') {
            ptr++;
        }
    }
    return 0;
}

static int validate_action_id(const char *value)
{
    size_t index;
    size_t len = strlen(value);

    if (len == 0 || len > 80) {
        return 0;
    }
    for (index = 0; index < len; index++) {
        unsigned char ch = (unsigned char)value[index];
        if (
            (ch >= 'a' && ch <= 'z')
            || (ch >= 'A' && ch <= 'Z')
            || (ch >= '0' && ch <= '9')
            || ch == '_' || ch == '.' || ch == ':' || ch == '-'
        ) {
            continue;
        }
        return 0;
    }
    return 1;
}

static int validate_alarm_command(const char *value)
{
    return strcmp(value, "arm_away") == 0
        || strcmp(value, "arm_home") == 0
        || strcmp(value, "arm_night") == 0
        || strcmp(value, "arm_custom_bypass") == 0
        || strcmp(value, "arm_vacation") == 0
        || strcmp(value, "disarm") == 0;
}

static int validate_alarm_code(const char *value)
{
    size_t len = strlen(value);

    if (len == 0 || len > 32) {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        if (!isdigit((unsigned char)value[index])) {
            return 0;
        }
    }
    return 1;
}

static int validate_event_name(const char *value)
{
    size_t len = strlen(value);

    if (len == 0 || len >= 64) {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        unsigned char ch = (unsigned char)value[index];
        if (
            (ch >= 'a' && ch <= 'z')
            || (ch >= 'A' && ch <= 'Z')
            || (ch >= '0' && ch <= '9')
            || ch == '_' || ch == '.' || ch == '-'
        ) {
            continue;
        }
        return 0;
    }
    return 1;
}

static int display_bridge_runtime_active(const struct agent_runtime *runtime)
{
    return runtime != NULL
        && runtime->display_bridge_registered
        && runtime->display_bridge_webhook_url[0] != '\0'
        && runtime->display_bridge_shared_secret[0] != '\0';
}

static int display_bridge_runtime_disabled(const struct agent_runtime *runtime)
{
    return runtime != NULL && runtime->display_bridge_disabled;
}

static void fnv1a64_fingerprint(const char *value, char *output, size_t output_len)
{
    unsigned long long hash = 1469598103934665603ULL;
    const unsigned char *ptr = (const unsigned char *)value;

    while (*ptr != '\0') {
        hash ^= (unsigned long long)*ptr++;
        hash *= 1099511628211ULL;
    }
    snprintf(output, output_len, "fnv1a64:%016llx", hash);
}

static void display_bridge_callback_fingerprint(
    int enabled,
    const char *webhook_url,
    const char *shared_secret,
    char *output,
    size_t output_len
)
{
    char material[C300X_MAX_URL_LEN + C300X_MAX_TOKEN_LEN + 16];

    snprintf(
        material,
        sizeof(material),
        "%d\n%s\n%s",
        enabled ? 1 : 0,
        enabled ? webhook_url : "",
        enabled ? shared_secret : ""
    );
    fnv1a64_fingerprint(material, output, output_len);
}

static void runtime_set_wake_reason(struct agent_runtime *runtime, const char *reason)
{
    if (runtime == NULL || reason == NULL || reason[0] == '\0') {
        return;
    }
    snprintf(runtime->last_wake_reason, sizeof(runtime->last_wake_reason), "%s", reason);
}

static int count_open_fds(void)
{
    int count = 0;
    DIR *dir = opendir("/proc/self/fd");
    struct dirent *entry;

    if (dir == NULL) {
        return -1;
    }
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        count++;
    }
    closedir(dir);
    return count;
}

static void record_agent_write(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const char *write_class,
    const char *reason
)
{
    char write_class_json[C300X_JSON_QUOTED_LEN(sizeof(runtime->last_write_class))];
    char reason_json[C300X_JSON_QUOTED_LEN(sizeof(runtime->last_write_reason))];
    char qml_patch_last_action_json[C300X_JSON_QUOTED_LEN(sizeof(runtime->qml_patch_last_action))];
    char data[512];

    if (runtime == NULL) {
        return;
    }
    runtime->agent_write_count++;
    runtime->last_write_at = time(NULL);
    snprintf(runtime->last_write_class, sizeof(runtime->last_write_class), "%s", write_class);
    snprintf(runtime->last_write_reason, sizeof(runtime->last_write_reason), "%s", reason);
    if (strcmp(write_class, "subscription") == 0) {
        runtime->subscription_store_writes++;
    } else if (strcmp(write_class, "qml_patch") == 0) {
        snprintf(runtime->qml_patch_last_action, sizeof(runtime->qml_patch_last_action), "%s", reason);
    }
    if (config == NULL) {
        return;
    }
    if (!has_matching_subscription(runtime, "agent.diagnostics_changed")) {
        return;
    }
    json_string(runtime->last_write_class, write_class_json, sizeof(write_class_json));
    json_string(runtime->last_write_reason, reason_json, sizeof(reason_json));
    json_string(
        runtime->qml_patch_last_action,
        qml_patch_last_action_json,
        sizeof(qml_patch_last_action_json)
    );
    if (
        snprintf(
            data,
            sizeof(data),
            "{\"agent_write_count\":%lu,\"last_write_at\":%ld,\"last_write_class\":%s,\"last_write_reason\":%s,\"subscription_store_writes\":%lu,\"qml_patch_last_action\":%s}",
            runtime->agent_write_count,
            (long)runtime->last_write_at,
            write_class_json,
            reason_json,
            runtime->subscription_store_writes,
            qml_patch_last_action_json
        ) >= (int)sizeof(data)
    ) {
        return;
    }
    dispatch_event(config, runtime, "agent.diagnostics_changed", data, 30);
}

static int agent_base_dir(const struct c300x_config *config, char *out, size_t out_len)
{
    if (out_len == 0 || config == NULL || config->config_path[0] == '\0') {
        return 0;
    }
    if (snprintf(out, out_len, "%s", config->config_path) >= (int)out_len) {
        return 0;
    }
    if (!path_parent_inplace(out)) {
        return 0;
    }
    return out[0] != '\0';
}

static int agent_update_stage_dir(
    const struct c300x_config *config,
    char *out,
    size_t out_len
)
{
    char base[C300X_MAX_PATH_LEN];

    if (!agent_base_dir(config, base, sizeof(base))) {
        return 0;
    }
    return snprintf(out, out_len, "%s/%s", base, C300X_AGENT_UPDATE_STAGE) < (int)out_len;
}

static int agent_bundle_manifest_path(
    const struct c300x_config *config,
    char *out,
    size_t out_len
)
{
    char base[C300X_MAX_PATH_LEN];

    if (!agent_base_dir(config, base, sizeof(base))) {
        return 0;
    }
    return snprintf(out, out_len, "%s/%s", base, C300X_AGENT_BUNDLE_MANIFEST) < (int)out_len;
}

static int safe_agent_update_path(const char *path)
{
    size_t len;
    const char *prefix = "device_agent/";

    if (path == NULL || path[0] == '\0' || path[0] == '/' || strstr(path, "\\") != NULL) {
        return 0;
    }
    len = strlen(path);
    if (len >= C300X_MAX_PATH_LEN || strncmp(path, prefix, strlen(prefix)) != 0) {
        return 0;
    }
    if (strstr(path, "/../") != NULL || strstr(path, "../") == path || strstr(path, "/..") == path + len - 3) {
        return 0;
    }
    if (
        strcmp(path, "device_agent/armhf/c300x-agent-native") == 0
        || strcmp(path, "device_agent/scripts/qml_patch.sh") == 0
        || strcmp(path, "device_agent/scripts/remove_agent.sh") == 0
        || strcmp(path, "device_agent/scripts/bootstrap_firewall.sh") == 0
        || strcmp(path, "device_agent/init/c300x-native-agent") == 0
        || strcmp(path, "device_agent/bundle.json") == 0
        || strncmp(path, "device_agent/qml/", strlen("device_agent/qml/")) == 0
    ) {
        return 1;
    }
    return 0;
}

static int agent_update_stage_path(
    const struct c300x_config *config,
    const char *bundle_path,
    char *out,
    size_t out_len
)
{
    char stage_dir[C300X_MAX_PATH_LEN];

    if (!safe_agent_update_path(bundle_path) || !agent_update_stage_dir(config, stage_dir, sizeof(stage_dir))) {
        return 0;
    }
    return snprintf(out, out_len, "%s/%s", stage_dir, bundle_path) < (int)out_len;
}

static int agent_update_target_path(
    const struct c300x_config *config,
    const char *bundle_path,
    char *out,
    size_t out_len
)
{
    char base[C300X_MAX_PATH_LEN];
    const char *relative_target = NULL;

    if (!safe_agent_update_path(bundle_path) || !agent_base_dir(config, base, sizeof(base))) {
        return 0;
    }
    if (strcmp(bundle_path, "device_agent/armhf/c300x-agent-native") == 0) {
        relative_target = "c300x-agent-native";
    } else if (strcmp(bundle_path, "device_agent/scripts/qml_patch.sh") == 0) {
        relative_target = "qml_patch.sh";
    } else if (strcmp(bundle_path, "device_agent/scripts/remove_agent.sh") == 0) {
        relative_target = "remove_agent.sh";
    } else if (strcmp(bundle_path, "device_agent/scripts/bootstrap_firewall.sh") == 0) {
        relative_target = "bootstrap_firewall.sh";
    } else if (strcmp(bundle_path, "device_agent/init/c300x-native-agent") == 0) {
        if (snprintf(out, out_len, "%s", C300X_AGENT_INIT_SCRIPT) >= (int)out_len) {
            return 0;
        }
        return 1;
    } else if (strcmp(bundle_path, "device_agent/bundle.json") == 0) {
        relative_target = C300X_AGENT_BUNDLE_MANIFEST;
    } else if (strncmp(bundle_path, "device_agent/qml/", strlen("device_agent/qml/")) == 0) {
        relative_target = bundle_path + strlen("device_agent/");
    }
    if (relative_target == NULL) {
        return 0;
    }
    return snprintf(out, out_len, "%s/%s", base, relative_target) < (int)out_len;
}

static int read_agent_bundle_metadata(
    const struct c300x_config *config,
    char *bundle_hash,
    size_t bundle_hash_len,
    char *agent_version,
    size_t agent_version_len,
    char *api_version,
    size_t api_version_len
)
{
    char manifest_path[C300X_MAX_PATH_LEN];
    char manifest[8192];
    int truncated = 0;

    if (bundle_hash_len > 0) {
        bundle_hash[0] = '\0';
    }
    if (agent_version_len > 0) {
        agent_version[0] = '\0';
    }
    if (api_version_len > 0) {
        api_version[0] = '\0';
    }
    if (!agent_bundle_manifest_path(config, manifest_path, sizeof(manifest_path))) {
        return 0;
    }
    if (!read_bounded_text_file(manifest_path, manifest, sizeof(manifest), &truncated) || truncated) {
        return 0;
    }
    json_string_field(manifest, "bundle_hash", bundle_hash, bundle_hash_len);
    json_string_field(manifest, "agent_version", agent_version, agent_version_len);
    if (agent_version_len > 0 && agent_version[0] == '\0') {
        json_string_field(manifest, "version", agent_version, agent_version_len);
    }
    json_string_field(manifest, "api_version", api_version, api_version_len);
    return bundle_hash[0] != '\0' || agent_version[0] != '\0' || api_version[0] != '\0';
}

static int agent_update_manifest_field_changed(
    const char *installed_manifest,
    const char *staged_manifest,
    const char *field
)
{
    char installed_value[C300X_AGENT_BUNDLE_HASH_LEN];
    char staged_value[C300X_AGENT_BUNDLE_HASH_LEN];

    json_string_field(staged_manifest, field, staged_value, sizeof(staged_value));
    if (staged_value[0] == '\0') {
        return 0;
    }
    if (installed_manifest == NULL || installed_manifest[0] == '\0') {
        return 1;
    }
    json_string_field(installed_manifest, field, installed_value, sizeof(installed_value));
    return !constant_time_equal(
        installed_value,
        strlen(installed_value),
        staged_value
    );
}

static int display_bridge_active(
    const struct c300x_config *config,
    const struct agent_runtime *runtime
)
{
    if (display_bridge_runtime_active(runtime)) {
        return 1;
    }
    if (display_bridge_runtime_disabled(runtime)) {
        return 0;
    }
    return config->display_bridge_enabled;
}

static const char *display_bridge_webhook_url(
    const struct c300x_config *config,
    const struct agent_runtime *runtime
)
{
    if (display_bridge_runtime_active(runtime)) {
        return runtime->display_bridge_webhook_url;
    }
    if (display_bridge_runtime_disabled(runtime)) {
        return "";
    }
    return config->home_assistant_webhook_url;
}

static const char *display_bridge_shared_secret(
    const struct c300x_config *config,
    const struct agent_runtime *runtime
)
{
    if (display_bridge_runtime_active(runtime)) {
        return runtime->display_bridge_shared_secret;
    }
    if (display_bridge_runtime_disabled(runtime)) {
        return "";
    }
    return config->home_assistant_shared_secret;
}

static int forward_to_homeassistant(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const char *body,
    char *response,
    size_t response_len
)
{
    char host[256];
    char host_header[288];
    char port[16];
    char path[256];
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    struct addrinfo *item;
    int fd = -1;
    char header[1024];
    const char *webhook_url = display_bridge_webhook_url(config, runtime);
    const char *shared_secret = display_bridge_shared_secret(config, runtime);
    int ok = 0;
    ssize_t receive_result;

    if (response_len > 0) {
        response[0] = '\0';
    }
    if (!runtime_network_online(runtime, time(NULL))) {
        return 0;
    }
    if (webhook_url[0] == '\0') {
        return 0;
    }
    if (!parse_http_url(
        webhook_url,
        host,
        sizeof(host),
        port,
        sizeof(port),
        path,
        sizeof(path)
    )) {
        return 0;
    }

    memset(&hints, 0, sizeof(hints));
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_family = AF_UNSPEC;
    if (getaddrinfo(host, port, &hints, &result) != 0) {
        return 0;
    }
    http_host_header_value(host, port, host_header, sizeof(host_header));
    for (item = result; item != NULL; item = item->ai_next) {
        fd = socket(item->ai_family, item->ai_socktype, item->ai_protocol);
        if (fd < 0) {
            continue;
        }
        set_fd_cloexec(fd);
        set_socket_timeout(fd, config->home_assistant_request_timeout_ms);
        if (connect(fd, item->ai_addr, item->ai_addrlen) == 0) {
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(result);
    if (fd < 0) {
        return 0;
    }

    snprintf(
        header,
        sizeof(header),
        "POST %s HTTP/1.1\r\n"
        "Host: %s\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %zu\r\n"
        "%s%s%s"
        "Connection: close\r\n"
        "\r\n",
        path,
        host_header,
        strlen(body),
        shared_secret[0] != '\0' ? "X-Bticino-C300X-Secret: " : "",
        shared_secret[0] != '\0' ? shared_secret : "",
        shared_secret[0] != '\0' ? "\r\n" : ""
    );

    if (send(fd, header, strlen(header), MSG_NOSIGNAL) > 0
        && send(fd, body, strlen(body), MSG_NOSIGNAL) > 0) {
        size_t received = 0;
        while (received + 1 < response_len) {
            receive_result = recv(fd, response + received, response_len - received - 1, 0);
            if (receive_result <= 0) {
                break;
            }
            received += (size_t)receive_result;
        }
        if (received > 0) {
            response[received] = '\0';
        }
    }
    close(fd);

    if (response_len > 0) {
        const char *status_end = strstr(response, "\r\n");
        if (status_end != NULL) {
            size_t status_len = (size_t)(status_end - response);
            if (status_len > 0) {
                char status_line[32] = {0};
                snprintf(status_line, sizeof(status_line), "%.*s", (int)status_len, response);
                if (strncmp(status_line, "HTTP/1.1 2", 9) == 0 || strncmp(status_line, "HTTP/1.0 2", 9) == 0) {
                    ok = 1;
                }
            }
        }
        if (ok) {
            const char *separator = strstr(response, "\r\n\r\n");
            if (separator != NULL) {
                const char *body = separator + 4;
                size_t body_len = strlen(body);
                if (body_len >= response_len) {
                    body_len = response_len - 1;
                }
                memmove(response, body, body_len);
                response[body_len] = '\0';
            }
            if (response[0] == '\0') {
                snprintf(response, response_len, "{}\n");
            }
        } else if (response[0] == '\0') {
            snprintf(response, response_len, "{}\n");
            ok = 1;
        }
    }

    if (ok) {
        mark_home_assistant_callback_seen(runtime, time(NULL));
    }
    return ok;
}

static void mark_home_assistant_callback_seen(struct agent_runtime *runtime, time_t now)
{
    if (runtime == NULL) {
        return;
    }
    runtime->home_assistant_connected_this_run = 1;
    runtime->home_assistant_last_seen_at = now;
}

static int address_is_valid(const char *value)
{
    size_t len = strlen(value);
    if (len == 0 || len >= C300X_MAX_ADDRESS_LEN) {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        if (!isdigit((unsigned char)value[index]) && value[index] != '#') {
            return 0;
        }
    }
    return 1;
}

static void json_string_field(const char *body, const char *field, char *out, size_t out_len)
{
    char pattern[64];
    const char *found;
    const char *ptr;
    size_t written = 0;

    if (out_len > 0) {
        out[0] = '\0';
    }
    snprintf(pattern, sizeof(pattern), "\"%s\"", field);
    found = strstr(body, pattern);
    if (found == NULL) {
        return;
    }
    ptr = strchr(found + strlen(pattern), ':');
    if (ptr == NULL) {
        return;
    }
    ptr++;
    while (*ptr != '\0' && isspace((unsigned char)*ptr)) {
        ptr++;
    }
    if (*ptr != '"') {
        return;
    }
    ptr++;
    while (*ptr != '\0' && *ptr != '"' && written + 1 < out_len) {
        if (*ptr == '\\' && ptr[1] != '\0') {
            ptr++;
        }
        out[written++] = *ptr++;
    }
    if (out_len > 0) {
        out[written] = '\0';
    }
}

static int json_bool_field(const char *body, const char *field, int *out)
{
    char pattern[64];
    const char *found;
    const char *ptr;

    snprintf(pattern, sizeof(pattern), "\"%s\"", field);
    found = strstr(body, pattern);
    if (found == NULL) {
        return 0;
    }
    ptr = strchr(found + strlen(pattern), ':');
    if (ptr == NULL) {
        return 0;
    }
    ptr++;
    while (*ptr != '\0' && isspace((unsigned char)*ptr)) {
        ptr++;
    }
    if (strncmp(ptr, "true", 4) == 0) {
        *out = 1;
        return 1;
    }
    if (strncmp(ptr, "false", 5) == 0) {
        *out = 0;
        return 1;
    }
    return 0;
}

static int json_int_field(const char *body, const char *field, int *out)
{
    char pattern[64];
    const char *found;
    const char *ptr;
    char *end = NULL;
    long value;

    snprintf(pattern, sizeof(pattern), "\"%s\"", field);
    found = strstr(body, pattern);
    if (found == NULL) {
        return 0;
    }
    ptr = strchr(found + strlen(pattern), ':');
    if (ptr == NULL) {
        return 0;
    }
    ptr++;
    while (*ptr != '\0' && isspace((unsigned char)*ptr)) {
        ptr++;
    }
    errno = 0;
    value = strtol(ptr, &end, 10);
    if (errno != 0 || end == ptr) {
        return 0;
    }
    *out = (int)value;
    return 1;
}

static int header_value(const struct request *request, const char *name, char *out, size_t out_len)
{
    const char *line = request->headers;
    const size_t name_len = strlen(name);

    if (out_len > 0) {
        out[0] = '\0';
    }
    while (*line != '\0') {
        const char *line_end = strstr(line, "\r\n");
        const char *value;
        size_t value_len;

        if (line_end == NULL) {
            line_end = line + strlen(line);
        }
        if ((size_t)(line_end - line) > name_len && strncasecmp(line, name, name_len) == 0 && line[name_len] == ':') {
            value = line + name_len + 1;
            while (value < line_end && (*value == ' ' || *value == '\t')) {
                value++;
            }
            value_len = (size_t)(line_end - value);
            while (value_len > 0 && (value[value_len - 1] == ' ' || value[value_len - 1] == '\t')) {
                value_len--;
            }
            if (value_len >= out_len) {
                value_len = out_len > 0 ? out_len - 1 : 0;
            }
            if (out_len > 0) {
                memcpy(out, value, value_len);
                out[value_len] = '\0';
            }
            return 1;
        }
        if (*line_end == '\0') {
            break;
        }
        line = line_end + 2;
    }
    return 0;
}

static void sleep_ms(int delay_ms)
{
    struct timespec requested;
    struct timespec remaining;

    requested.tv_sec = delay_ms / 1000;
    requested.tv_nsec = (long)(delay_ms % 1000) * 1000000L;
    while (nanosleep(&requested, &remaining) != 0 && errno == EINTR) {
        requested = remaining;
    }
}

static void set_socket_timeout(int fd, int timeout_ms)
{
    struct timeval timeout;
    timeout.tv_sec = timeout_ms / 1000;
    timeout.tv_usec = (timeout_ms % 1000) * 1000;
    (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
}

static void set_fd_nonblocking(int fd)
{
    int enabled = 1;

    (void)ioctl(fd, FIONBIO, &enabled);
}

static void set_fd_cloexec(int fd)
{
    (void)ioctl(fd, FIOCLEX);
}

static void allow_socket_reuse(int fd)
{
    int enabled = 1;
    (void)setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &enabled, sizeof(enabled));
}

static int client_is_loopback(int client_fd)
{
    struct sockaddr_storage address;
    socklen_t address_len = sizeof(address);

    if (getpeername(client_fd, (struct sockaddr *)&address, &address_len) != 0) {
        return 0;
    }
    if (address.ss_family == AF_INET) {
        const struct sockaddr_in *inet_address = (const struct sockaddr_in *)&address;
        return (ntohl(inet_address->sin_addr.s_addr) & 0xff000000U) == 0x7f000000U;
    }
    if (address.ss_family == AF_INET6) {
        const struct sockaddr_in6 *inet6_address = (const struct sockaddr_in6 *)&address;
        static const unsigned char loopback[16] = {
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1
        };
        return memcmp(&inet6_address->sin6_addr, loopback, sizeof(loopback)) == 0;
    }
    return 0;
}

static int path_is_directory(const char *path)
{
    DIR *directory;
    if (path == NULL || path[0] == '\0') {
        return 0;
    }
    directory = opendir(path);
    if (directory == NULL) {
        return 0;
    }
    closedir(directory);
    return 1;
}

static int path_exists(const char *path)
{
    if (path == NULL || path[0] == '\0') {
        return 0;
    }
    return access(path, F_OK) == 0;
}

static int wait_for_path_absent(const char *path, int timeout_ms)
{
    const int interval_ms = 100;
    int waited_ms = 0;

    if (path == NULL || path[0] == '\0') {
        return 0;
    }
    while (path_exists(path)) {
        if (waited_ms >= timeout_ms) {
            return 0;
        }
        sleep_ms(interval_ms);
        waited_ms += interval_ms;
    }
    return 1;
}

static int path_is_symlink(const char *path, int *is_symlink)
{
    char target;
    ssize_t read_len;

    if (is_symlink != NULL) {
        *is_symlink = 0;
    }
    if (path == NULL || path[0] == '\0') {
        errno = EINVAL;
        return 0;
    }
    read_len = readlink(path, &target, sizeof(target));
    if (read_len >= 0) {
        if (is_symlink != NULL) {
            *is_symlink = 1;
        }
        return 1;
    }
    if (errno == EINVAL) {
        return 1;
    }
    return 0;
}

static int read_bounded_text_file(
    const char *path,
    char *out,
    size_t out_len,
    int *truncated
)
{
    FILE *file;
    size_t read_len;

    if (truncated != NULL) {
        *truncated = 0;
    }
    if (out_len == 0) {
        return 0;
    }
    out[0] = '\0';
    if (path == NULL || path[0] == '\0') {
        return 0;
    }
    file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    read_len = fread(out, 1, out_len - 1, file);
    out[read_len] = '\0';
    if (truncated != NULL && read_len == out_len - 1 && fgetc(file) != EOF) {
        *truncated = 1;
    }
    fclose(file);
    while (read_len > 0 && (out[read_len - 1] == '\n' || out[read_len - 1] == '\r')) {
        out[--read_len] = '\0';
    }
    return read_len > 0;
}

static int path_parent_inplace(char *path)
{
    size_t len;
    char *slash;

    if (path == NULL || path[0] == '\0') {
        return 0;
    }
    len = strlen(path);
    while (len > 1 && path[len - 1] == '/') {
        path[len - 1] = '\0';
        len--;
    }
    slash = strrchr(path, '/');
    if (slash == NULL) {
        return 0;
    }
    if (slash == path) {
        path[1] = '\0';
        return 1;
    }
    *slash = '\0';
    return 1;
}

static int mkdir_p(const char *path, mode_t mode)
{
    char buffer[C300X_MAX_PATH_LEN];
    size_t len;

    if (path == NULL || path[0] != '/') {
        return 0;
    }
    if (snprintf(buffer, sizeof(buffer), "%s", path) >= (int)sizeof(buffer)) {
        return 0;
    }
    len = strlen(buffer);
    while (len > 1 && buffer[len - 1] == '/') {
        buffer[--len] = '\0';
    }
    for (char *ptr = buffer + 1; *ptr != '\0'; ptr++) {
        if (*ptr != '/') {
            continue;
        }
        *ptr = '\0';
        if (mkdir(buffer, mode) != 0 && errno != EEXIST) {
            *ptr = '/';
            return 0;
        }
        *ptr = '/';
    }
    return mkdir(buffer, mode) == 0 || errno == EEXIST;
}

static int mkdir_parent(const char *path, mode_t mode)
{
    char parent[C300X_MAX_PATH_LEN];

    if (snprintf(parent, sizeof(parent), "%s", path) >= (int)sizeof(parent)) {
        return 0;
    }
    if (!path_parent_inplace(parent)) {
        return 0;
    }
    return mkdir_p(parent, mode);
}

static int remove_tree(const char *path)
{
    DIR *directory;
    struct dirent *entry;

    directory = opendir(path);
    if (directory == NULL) {
        return errno == ENOENT;
    }
    while ((entry = readdir(directory)) != NULL) {
        char child[C300X_MAX_PATH_LEN];
        DIR *child_directory;

        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        if (snprintf(child, sizeof(child), "%s/%s", path, entry->d_name) >= (int)sizeof(child)) {
            closedir(directory);
            return 0;
        }
        child_directory = opendir(child);
        if (child_directory != NULL) {
            closedir(child_directory);
            if (!remove_tree(child)) {
                closedir(directory);
                return 0;
            }
        } else if (unlink(child) != 0) {
            closedir(directory);
            return 0;
        }
    }
    closedir(directory);
    return rmdir(path) == 0 || errno == ENOENT;
}

static int file_size_matches(const char *path, long expected_size)
{
    FILE *file;
    long size;

    file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return 0;
    }
    size = ftell(file);
    fclose(file);
    if (size < 0) {
        return 0;
    }
    return size == expected_size;
}

static int parse_file_mode(const char *value, mode_t fallback, mode_t *mode)
{
    char *endptr = NULL;
    long parsed;

    if (mode == NULL) {
        return 0;
    }
    if (value == NULL || value[0] == '\0') {
        *mode = fallback;
        return 1;
    }
    errno = 0;
    parsed = strtol(value, &endptr, 8);
    if (errno != 0 || endptr == value || *endptr != '\0' || parsed < 0 || parsed > 0777) {
        return 0;
    }
    *mode = (mode_t)parsed;
    return 1;
}

static int write_binary_chunk(
    const char *path,
    const unsigned char *data,
    size_t data_len,
    long offset,
    mode_t mode
)
{
    FILE *file;

    if (path == NULL || path[0] == '\0' || offset < 0) {
        return 0;
    }
    if (!mkdir_parent(path, 0755)) {
        return 0;
    }
    if (offset == 0) {
        file = fopen(path, "wb");
    } else {
        if (!file_size_matches(path, offset)) {
            return 0;
        }
        file = fopen(path, "ab");
    }
    if (file == NULL) {
        return 0;
    }
    if (data_len > 0 && fwrite(data, 1, data_len, file) != data_len) {
        (void)fclose(file);
        return 0;
    }
    if (fclose(file) != 0) {
        return 0;
    }
    (void)chmod(path, mode);
    return 1;
}

static int copy_binary_file(const char *source, const char *target, mode_t mode)
{
    char temporary_path[C300X_MAX_PATH_LEN + 8];
    unsigned char buffer[4096];
    FILE *in;
    FILE *out;
    size_t read_len;

    if (!mkdir_parent(target, 0755)) {
        return 0;
    }
    if (snprintf(temporary_path, sizeof(temporary_path), "%s.tmp", target) >= (int)sizeof(temporary_path)) {
        return 0;
    }
    in = fopen(source, "rb");
    if (in == NULL) {
        return 0;
    }
    out = fopen(temporary_path, "wb");
    if (out == NULL) {
        fclose(in);
        return 0;
    }
    while ((read_len = fread(buffer, 1, sizeof(buffer), in)) > 0) {
        if (fwrite(buffer, 1, read_len, out) != read_len) {
            fclose(in);
            fclose(out);
            (void)unlink(temporary_path);
            return 0;
        }
    }
    if (ferror(in)) {
        fclose(in);
        fclose(out);
        (void)unlink(temporary_path);
        return 0;
    }
    {
        int close_in = fclose(in);
        int close_out = fclose(out);
        if (close_in != 0 || close_out != 0) {
            (void)unlink(temporary_path);
            return 0;
        }
    }
    (void)chmod(temporary_path, mode);
    if (rename(temporary_path, target) != 0) {
        (void)unlink(temporary_path);
        return 0;
    }
    (void)chmod(target, mode);
    return 1;
}

static int file_content_matches(const char *source, const char *target)
{
    char source_sha[65];
    char target_sha[65];

    if (
        !c300x_sha256_file_hex(source, source_sha, sizeof(source_sha))
        || !c300x_sha256_file_hex(target, target_sha, sizeof(target_sha))
    ) {
        return 0;
    }
    return constant_time_equal(source_sha, strlen(source_sha), target_sha);
}

static int copy_binary_file_if_changed(
    const char *source,
    const char *target,
    mode_t mode,
    int *changed
)
{
    if (changed != NULL) {
        *changed = 0;
    }
    if (file_content_matches(source, target)) {
        return 1;
    }
    if (!copy_binary_file(source, target, mode)) {
        return 0;
    }
    if (changed != NULL) {
        *changed = 1;
    }
    return 1;
}

static int base64_value(int ch)
{
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

static int base64_decode_bytes(
    const char *input,
    unsigned char *output,
    size_t output_len,
    size_t *decoded_len
)
{
    int value = 0;
    int bits = -8;
    size_t used = 0;

    if (decoded_len != NULL) {
        *decoded_len = 0;
    }
    for (const unsigned char *ptr = (const unsigned char *)input; *ptr != '\0'; ptr++) {
        int sextet;

        if (isspace(*ptr)) {
            continue;
        }
        if (*ptr == '=') {
            break;
        }
        sextet = base64_value(*ptr);
        if (sextet < 0) {
            return 0;
        }
        value = (value << 6) | sextet;
        bits += 6;
        if (bits >= 0) {
            if (used >= output_len) {
                return 0;
            }
            output[used++] = (unsigned char)((value >> bits) & 0xff);
            bits -= 8;
        }
    }
    if (decoded_len != NULL) {
        *decoded_len = used;
    }
    return 1;
}

static int sha256_hex_matches(const char *path, const char *expected)
{
    char actual[65];

    if (expected == NULL || strlen(expected) != 64) {
        return 0;
    }
    if (!c300x_sha256_file_hex(path, actual, sizeof(actual))) {
        return 0;
    }
    return constant_time_equal(actual, strlen(actual), expected);
}

static int safe_voicemail_entry_name(const char *name)
{
    size_t len;
    if (name == NULL) {
        return 0;
    }
    if (strcmp(name, ".") == 0 || strcmp(name, "..") == 0) {
        return 0;
    }
    len = strlen(name);
    if (len == 0 || len >= C300X_MAX_VOICEMAIL_ID_LEN) {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        unsigned char ch = (unsigned char)name[index];
        if (
            (ch >= 'a' && ch <= 'z')
            || (ch >= 'A' && ch <= 'Z')
            || (ch >= '0' && ch <= '9')
            || ch == '_' || ch == '.' || ch == '-'
        ) {
            continue;
        }
        return 0;
    }
    return 1;
}

static const char *video_mime_type_for_name(const char *name)
{
    const char *extension = strrchr(name, '.');
    if (extension == NULL) {
        return "application/octet-stream";
    }
    if (strcasecmp(extension, ".avi") == 0) {
        return "video/x-msvideo";
    }
    if (strcasecmp(extension, ".mkv") == 0) {
        return "video/x-matroska";
    }
    if (strcasecmp(extension, ".mp4") == 0) {
        return "video/mp4";
    }
    return "application/octet-stream";
}

static const char *audio_mime_type_for_name(const char *name)
{
    const char *extension = strrchr(name, '.');
    if (extension == NULL) {
        return "application/octet-stream";
    }
    if (strcasecmp(extension, ".wav") == 0) {
        return "audio/wav";
    }
    if (strcasecmp(extension, ".mp3") == 0) {
        return "audio/mpeg";
    }
    if (strcasecmp(extension, ".ogg") == 0) {
        return "audio/ogg";
    }
    return "application/octet-stream";
}

static int regular_file_info(
    const char *path,
    long long *size,
    int *is_symlink
)
{
    FILE *file;
    long file_size;

    if (is_symlink != NULL) {
        *is_symlink = 0;
    }
    if (size != NULL) {
        *size = 0;
    }
    if (!path_is_symlink(path, is_symlink)) {
        return 0;
    }
    if (is_symlink != NULL && *is_symlink) {
        return 0;
    }
    file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return 0;
    }
    file_size = ftell(file);
    fclose(file);
    if (file_size < 0) {
        return 0;
    }
    if (size != NULL) {
        *size = (long long)file_size;
    }
    return 1;
}

static int find_answering_message_video(
    const struct voicemail_runtime *voicemail,
    const char *message_id,
    char *path,
    size_t path_len,
    const char **content_type,
    long long *size
)
{
    static const char *filenames[] = {"aswm.avi", "aswm.mkv", "aswm.mp4"};
    char message_dir[C300X_MAX_PATH_LEN];
    char info_path[C300X_MAX_PATH_LEN];
    int is_symlink = 0;

    if (path_len > 0) {
        path[0] = '\0';
    }
    if (content_type != NULL) {
        *content_type = "application/octet-stream";
    }
    if (size != NULL) {
        *size = 0;
    }
    if (
        voicemail == NULL
        || !voicemail->enabled
        || voicemail->root[0] == '\0'
        || !safe_voicemail_entry_name(message_id)
    ) {
        return 0;
    }
    if (snprintf(message_dir, sizeof(message_dir), "%s/%s", voicemail->root, message_id) >= (int)sizeof(message_dir)) {
        return 0;
    }
    if (!path_is_symlink(message_dir, &is_symlink) || is_symlink || !path_is_directory(message_dir)) {
        return 0;
    }
    if (snprintf(info_path, sizeof(info_path), "%s/msg_info.ini", message_dir) >= (int)sizeof(info_path) || !path_exists(info_path)) {
        return 0;
    }
    for (size_t index = 0; index < sizeof(filenames) / sizeof(filenames[0]); index++) {
        char candidate[C300X_MAX_PATH_LEN];
        long long candidate_size = 0;
        int file_is_symlink = 0;
        if (snprintf(candidate, sizeof(candidate), "%s/%s", message_dir, filenames[index]) >= (int)sizeof(candidate)) {
            continue;
        }
        if (!regular_file_info(candidate, &candidate_size, &file_is_symlink) || file_is_symlink) {
            continue;
        }
        snprintf(path, path_len, "%s", candidate);
        if (content_type != NULL) {
            *content_type = video_mime_type_for_name(filenames[index]);
        }
        if (size != NULL) {
            *size = candidate_size;
        }
        return 1;
    }
    return 0;
}

static int parse_memo_id(
    const char *memo_id,
    char *kind,
    size_t kind_len,
    char *entry_name,
    size_t entry_name_len
)
{
    const char *separator;
    const char *name_start;
    size_t parsed_kind_len;
    size_t parsed_name_len;

    if (kind_len > 0) {
        kind[0] = '\0';
    }
    if (entry_name_len > 0) {
        entry_name[0] = '\0';
    }
    if (memo_id == NULL || memo_id[0] == '\0') {
        return 0;
    }
    separator = strchr(memo_id, '/');
    if (separator == NULL || strchr(separator + 1, '/') != NULL) {
        return 0;
    }
    parsed_kind_len = (size_t)(separator - memo_id);
    name_start = separator + 1;
    parsed_name_len = strlen(name_start);
    if (
        parsed_kind_len == 0
        || parsed_kind_len >= kind_len
        || parsed_name_len == 0
        || parsed_name_len >= entry_name_len
    ) {
        return 0;
    }
    memcpy(kind, memo_id, parsed_kind_len);
    kind[parsed_kind_len] = '\0';
    snprintf(entry_name, entry_name_len, "%s", name_start);
    if (strcmp(kind, "text") != 0 && strcmp(kind, "voice") != 0) {
        return 0;
    }
    return safe_voicemail_entry_name(entry_name);
}

static int find_memo_audio(
    const struct voicemail_runtime *memos,
    const char *entry_name,
    char *path,
    size_t path_len,
    const char **content_type,
    long long *size
)
{
    static const char *filenames[] = {"audio.wav", "audio.mp3", "audio.ogg"};
    char memo_dir[C300X_MAX_PATH_LEN];
    char info_path[C300X_MAX_PATH_LEN];
    int is_symlink = 0;

    if (path_len > 0) {
        path[0] = '\0';
    }
    if (content_type != NULL) {
        *content_type = "application/octet-stream";
    }
    if (size != NULL) {
        *size = 0;
    }
    if (
        memos == NULL
        || !memos->enabled
        || memos->root[0] == '\0'
        || !safe_voicemail_entry_name(entry_name)
    ) {
        return 0;
    }
    if (snprintf(memo_dir, sizeof(memo_dir), "%s/%s", memos->root, entry_name) >= (int)sizeof(memo_dir)) {
        return 0;
    }
    if (!path_is_symlink(memo_dir, &is_symlink) || is_symlink || !path_is_directory(memo_dir)) {
        return 0;
    }
    if (snprintf(info_path, sizeof(info_path), "%s/msg_info.ini", memo_dir) >= (int)sizeof(info_path) || !path_exists(info_path)) {
        return 0;
    }
    for (size_t index = 0; index < sizeof(filenames) / sizeof(filenames[0]); index++) {
        char candidate[C300X_MAX_PATH_LEN];
        long long candidate_size = 0;
        int file_is_symlink = 0;
        if (snprintf(candidate, sizeof(candidate), "%s/%s", memo_dir, filenames[index]) >= (int)sizeof(candidate)) {
            continue;
        }
        if (!regular_file_info(candidate, &candidate_size, &file_is_symlink) || file_is_symlink) {
            continue;
        }
        snprintf(path, path_len, "%s", candidate);
        if (content_type != NULL) {
            *content_type = audio_mime_type_for_name(filenames[index]);
        }
        if (size != NULL) {
            *size = candidate_size;
        }
        return 1;
    }
    return 0;
}

static int entry_number_from_prefixed_name(const char *name, const char *prefix, int *number)
{
    const char *digits;
    char *endptr = NULL;
    long parsed;
    size_t prefix_len;

    if (number != NULL) {
        *number = 0;
    }
    if (name == NULL || prefix == NULL || number == NULL) {
        return 0;
    }
    prefix_len = strlen(prefix);
    if (strncmp(name, prefix, prefix_len) != 0 || name[prefix_len] == '\0') {
        return 0;
    }
    digits = name + prefix_len;
    errno = 0;
    parsed = strtol(digits, &endptr, 10);
    if (errno != 0 || endptr == digits || *endptr != '\0' || parsed <= 0 || parsed > INT_MAX) {
        return 0;
    }
    *number = (int)parsed;
    return 1;
}

static int send_answering_delete_command(
    const struct c300x_config *config,
    int entry_number,
    int directory,
    char *reply,
    size_t reply_len,
    char *error,
    size_t error_len
)
{
    char command[64];

    if (entry_number <= 0 || directory < 0) {
        if (error_len > 0) {
            snprintf(error, error_len, "%s", "invalid_answering_delete_target");
        }
        return 0;
    }
    snprintf(command, sizeof(command), "*8*94#%d#%d##", entry_number, directory);
    return c300x_openwebnet_send(config, command, reply, reply_len, error, error_len);
}

static const char *trim_ascii(char *value)
{
    char *start = value;
    char *end;
    while (*start != '\0' && isspace((unsigned char)*start)) {
        start++;
    }
    end = start + strlen(start);
    while (end > start && isspace((unsigned char)end[-1])) {
        end--;
    }
    *end = '\0';
    return start;
}

static void iso_time_from_unix(long long unix_time, char *out, size_t out_len)
{
    time_t now;
    struct tm tm_value;

    if (out_len == 0) {
        return;
    }
    out[0] = '\0';
    if (unix_time <= 0) {
        return;
    }
    now = (time_t)unix_time;
    if (gmtime_r(&now, &tm_value) == NULL) {
        return;
    }
    strftime(out, out_len, "%Y-%m-%dT%H:%M:%SZ", &tm_value);
}

static void read_voicemail_info(
    const char *info_path,
    int *read,
    char *date,
    size_t date_len,
    long long *unix_time
)
{
    FILE *file;
    char line[256];
    int in_section = 0;

    *read = -1;
    if (date_len > 0) {
        date[0] = '\0';
    }
    *unix_time = 0;

    file = fopen(info_path, "r");
    if (file == NULL) {
        return;
    }
    while (fgets(line, sizeof(line), file) != NULL) {
        char *value = line;
        const char *trimmed;
        char *equals;

        trimmed = trim_ascii(value);
        if (trimmed[0] == '\0' || trimmed[0] == ';' || trimmed[0] == '#') {
            continue;
        }
        if (trimmed[0] == '[') {
            in_section = strcmp(trimmed, "[Message Information]") == 0;
            continue;
        }
        if (!in_section) {
            continue;
        }
        equals = strchr((char *)trimmed, '=');
        if (equals == NULL) {
            continue;
        }
        *equals = '\0';
        {
            const char *key = trim_ascii((char *)trimmed);
            const char *field = trim_ascii(equals + 1);
            if (strcasecmp(key, "Read") == 0) {
                if (strcmp(field, "0") == 0) {
                    *read = 0;
                } else if (strcmp(field, "1") == 0) {
                    *read = 1;
                }
            } else if (strcasecmp(key, "Date") == 0) {
                snprintf(date, date_len, "%s", field);
            } else if (strcasecmp(key, "UnixTime") == 0) {
                char *parse_end = NULL;
                long long parsed = strtoll(field, &parse_end, 10);
                if (parse_end != field && parsed > 0) {
                    *unix_time = parsed;
                }
            }
        }
    }
    fclose(file);
}

static void voicemail_insert_sorted(
    struct voicemail_snapshot *snapshot,
    const struct voicemail_message *message,
    int max_messages
)
{
    int position = snapshot->message_count;
    if (position < max_messages) {
        snapshot->message_count++;
    } else if (message->timestamp <= snapshot->messages[max_messages - 1].timestamp) {
        return;
    } else {
        position = max_messages - 1;
    }
    snapshot->messages[position] = *message;
    while (
        position > 0
        && snapshot->messages[position].timestamp > snapshot->messages[position - 1].timestamp
    ) {
        struct voicemail_message tmp = snapshot->messages[position - 1];
        snapshot->messages[position - 1] = snapshot->messages[position];
        snapshot->messages[position] = tmp;
        position--;
    }
}

static void message_collection_read_snapshot(
    const struct voicemail_runtime *voicemail,
    const char *kind,
    struct voicemail_snapshot *snapshot
)
{
    DIR *root_dir;
    struct dirent *entry;
    int max_messages = voicemail->max_messages;

    memset(snapshot, 0, sizeof(*snapshot));
    snapshot->available = voicemail->enabled;
    if (!voicemail->enabled) {
        snprintf(snapshot->reason, sizeof(snapshot->reason), "disabled");
        return;
    }
    if (max_messages <= 0 || max_messages > C300X_MAX_VOICEMAIL_MESSAGES) {
        max_messages = C300X_MAX_VOICEMAIL_MESSAGES;
    }
    if (!path_is_directory(voicemail->root)) {
        snapshot->available = 0;
        snprintf(snapshot->reason, sizeof(snapshot->reason), "messages_dir_missing");
        return;
    }
    root_dir = opendir(voicemail->root);
    if (root_dir == NULL) {
        snapshot->available = 0;
        snprintf(snapshot->reason, sizeof(snapshot->reason), "messages_read_failed");
        return;
    }
    while ((entry = readdir(root_dir)) != NULL) {
        struct voicemail_message message;
        DIR *message_directory;
        char message_dir[C300X_MAX_PATH_LEN];
        char info_path[C300X_MAX_PATH_LEN];
        char thumbnail_path[C300X_MAX_PATH_LEN];
        char video_path[C300X_MAX_PATH_LEN];
        const char *video_mime_type = "application/octet-stream";
        long long video_size = 0;
        char audio_path[C300X_MAX_PATH_LEN];
        const char *audio_mime_type = "application/octet-stream";
        long long audio_size = 0;

        if (!safe_voicemail_entry_name(entry->d_name)) {
            continue;
        }
        if (snprintf(message_dir, sizeof(message_dir), "%s/%s", voicemail->root, entry->d_name) >= (int)sizeof(message_dir)) {
            continue;
        }
        message_directory = opendir(message_dir);
        if (message_directory == NULL) {
            continue;
        }
        closedir(message_directory);
        if (snprintf(info_path, sizeof(info_path), "%s/msg_info.ini", message_dir) >= (int)sizeof(info_path)) {
            continue;
        }
        if (!path_exists(info_path)) {
            continue;
        }
        memset(&message, 0, sizeof(message));
        {
            size_t entry_name_len = strlen(entry->d_name);
            if (entry_name_len >= sizeof(message.id)) {
                continue;
            }
            memcpy(message.id, entry->d_name, entry_name_len + 1);
        }
        snprintf(message.kind, sizeof(message.kind), "%s", kind != NULL ? kind : "");
        snprintf(message.dir_path, sizeof(message.dir_path), "%s", message_dir);
        read_voicemail_info(
            info_path,
            &message.read,
            message.date,
            sizeof(message.date),
            &message.unix_time
        );
        if (snprintf(thumbnail_path, sizeof(thumbnail_path), "%s/aswm.jpg", message_dir) < (int)sizeof(thumbnail_path)) {
            message.has_thumbnail = path_exists(thumbnail_path);
        }
        if (find_answering_message_video(
            voicemail,
            entry->d_name,
            video_path,
            sizeof(video_path),
            &video_mime_type,
            &video_size
        )) {
            message.has_video = 1;
            snprintf(message.video_mime_type, sizeof(message.video_mime_type), "%s", video_mime_type);
            message.video_size = video_size;
        }
        if (snprintf(thumbnail_path, sizeof(thumbnail_path), "%s/message.txt", message_dir) < (int)sizeof(thumbnail_path)) {
            message.has_text = path_exists(thumbnail_path);
            if (message.has_text && strcmp(message.kind, "text") == 0) {
                (void)read_bounded_text_file(
                    thumbnail_path,
                    message.text,
                    sizeof(message.text),
                    &message.text_truncated
                );
            }
        }
        if (
            strcmp(message.kind, "voice") == 0
            && find_memo_audio(
                voicemail,
                entry->d_name,
                audio_path,
                sizeof(audio_path),
                &audio_mime_type,
                &audio_size
            )
        ) {
            message.has_audio = 1;
            snprintf(message.audio_mime_type, sizeof(message.audio_mime_type), "%s", audio_mime_type);
            message.audio_size = audio_size;
        } else if (snprintf(thumbnail_path, sizeof(thumbnail_path), "%s/audio.wav", message_dir) < (int)sizeof(thumbnail_path)) {
            message.has_audio = path_exists(thumbnail_path);
            if (message.has_audio) {
                snprintf(message.audio_mime_type, sizeof(message.audio_mime_type), "%s", "audio/wav");
            }
        }
        message.timestamp = message.unix_time > 0 ? message.unix_time : 0;
        iso_time_from_unix(message.unix_time, message.iso_time, sizeof(message.iso_time));
        voicemail_insert_sorted(snapshot, &message, max_messages);
    }
    closedir(root_dir);

    snapshot->total = snapshot->message_count;
    for (int index = 0; index < snapshot->message_count; index++) {
        if (snapshot->messages[index].read == 0) {
            snapshot->unread++;
        } else if (snapshot->messages[index].read == 1) {
            snapshot->read++;
        }
        if (strcmp(snapshot->messages[index].kind, "text") == 0) {
            snapshot->text_total++;
        } else if (strcmp(snapshot->messages[index].kind, "voice") == 0) {
            snapshot->voice_total++;
        }
    }
    if (snapshot->message_count > 0) {
        if (snapshot->messages[0].iso_time[0] != '\0') {
            snprintf(snapshot->newest_at, sizeof(snapshot->newest_at), "%s", snapshot->messages[0].iso_time);
        } else if (snapshot->messages[0].date[0] != '\0') {
            snprintf(snapshot->newest_at, sizeof(snapshot->newest_at), "%s", snapshot->messages[0].date);
        }
    }
}

static void voicemail_read_snapshot(
    const struct voicemail_runtime *voicemail,
    struct voicemail_snapshot *snapshot
)
{
    message_collection_read_snapshot(voicemail, "", snapshot);
}

static unsigned long long signature_hash_bytes(unsigned long long hash, const void *ptr, size_t len)
{
    const unsigned char *data = (const unsigned char *)ptr;
    for (size_t index = 0; index < len; index++) {
        hash ^= (unsigned long long)data[index];
        hash *= 1099511628211ULL;
    }
    return hash;
}

static unsigned long long voicemail_signature(const struct voicemail_snapshot *snapshot)
{
    unsigned long long hash = 1469598103934665603ULL;
    hash = signature_hash_bytes(hash, &snapshot->available, sizeof(snapshot->available));
    hash = signature_hash_bytes(hash, &snapshot->total, sizeof(snapshot->total));
    hash = signature_hash_bytes(hash, &snapshot->unread, sizeof(snapshot->unread));
    hash = signature_hash_bytes(hash, &snapshot->read, sizeof(snapshot->read));
    hash = signature_hash_bytes(hash, snapshot->newest_at, strlen(snapshot->newest_at));
    for (int index = 0; index < snapshot->message_count; index++) {
        const struct voicemail_message *message = &snapshot->messages[index];
        hash = signature_hash_bytes(hash, message->id, strlen(message->id));
        hash = signature_hash_bytes(hash, &message->read, sizeof(message->read));
        hash = signature_hash_bytes(hash, &message->unix_time, sizeof(message->unix_time));
        hash = signature_hash_bytes(hash, &message->has_thumbnail, sizeof(message->has_thumbnail));
        hash = signature_hash_bytes(hash, &message->has_video, sizeof(message->has_video));
        hash = signature_hash_bytes(hash, message->video_mime_type, strlen(message->video_mime_type));
        hash = signature_hash_bytes(hash, &message->video_size, sizeof(message->video_size));
        hash = signature_hash_bytes(hash, &message->has_text, sizeof(message->has_text));
        hash = signature_hash_bytes(hash, &message->has_audio, sizeof(message->has_audio));
        hash = signature_hash_bytes(hash, message->audio_mime_type, strlen(message->audio_mime_type));
        hash = signature_hash_bytes(hash, &message->audio_size, sizeof(message->audio_size));
        hash = signature_hash_bytes(hash, &message->text_truncated, sizeof(message->text_truncated));
        hash = signature_hash_bytes(hash, message->text, strlen(message->text));
    }
    return hash;
}

static void drain_inotify_events(int fd)
{
    char buffer[4096];

    if (fd < 0) {
        return;
    }
    for (;;) {
        ssize_t read_size = read(fd, buffer, sizeof(buffer));
        if (read_size > 0) {
            continue;
        }
        if (read_size < 0 && errno == EINTR) {
            continue;
        }
        if (read_size < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            return;
        }
        return;
    }
}

static int read_inotify_change_events(int fd, int *structure_changed)
{
    char buffer[4096];
    int changed = 0;

    if (structure_changed != NULL) {
        *structure_changed = 0;
    }
    if (fd < 0) {
        return 0;
    }
    for (;;) {
        ssize_t read_size = read(fd, buffer, sizeof(buffer));
        size_t offset = 0;

        if (read_size > 0) {
            changed = 1;
            while (offset + sizeof(struct inotify_event) <= (size_t)read_size) {
                const struct inotify_event *event = (const struct inotify_event *)(const void *)(buffer + offset);
                if (
                    structure_changed != NULL
                    && (event->mask & (IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO | IN_DELETE_SELF | IN_MOVE_SELF)) != 0
                ) {
                    *structure_changed = 1;
                }
                offset += sizeof(struct inotify_event) + event->len;
            }
            continue;
        }
        if (read_size < 0 && errno == EINTR) {
            continue;
        }
        if (read_size < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            break;
        }
        break;
    }
    return changed;
}

static void voicemail_clear_watches(struct voicemail_runtime *voicemail)
{
    for (int index = 0; index < voicemail->watch_count; index++) {
        if (voicemail->watches[index].wd >= 0) {
            (void)inotify_rm_watch(voicemail->inotify_fd, voicemail->watches[index].wd);
        }
    }
    voicemail->watch_count = 0;
}

static void voicemail_add_watch(struct voicemail_runtime *voicemail, const char *path, int is_root)
{
    int wd;
    uint32_t mask;

    if (voicemail->inotify_fd < 0 || voicemail->watch_count >= C300X_MAX_VOICEMAIL_WATCHES) {
        return;
    }
    mask = C300X_MESSAGE_WATCH_MASK;
    wd = inotify_add_watch(voicemail->inotify_fd, path, mask);
    if (wd < 0) {
        return;
    }
    voicemail->watches[voicemail->watch_count].wd = wd;
    voicemail->watches[voicemail->watch_count].is_root = is_root;
    snprintf(voicemail->watches[voicemail->watch_count].path, sizeof(voicemail->watches[0].path), "%s", path);
    voicemail->watch_count++;
}

static void voicemail_add_entry_dir_watches(struct voicemail_runtime *voicemail)
{
    DIR *root_dir;
    struct dirent *entry;

    if (voicemail->inotify_fd < 0 || !path_is_directory(voicemail->root)) {
        return;
    }
    root_dir = opendir(voicemail->root);
    if (root_dir == NULL) {
        return;
    }
    while ((entry = readdir(root_dir)) != NULL) {
        char entry_dir[C300X_MAX_PATH_LEN];

        if (!safe_voicemail_entry_name(entry->d_name)) {
            continue;
        }
        if (snprintf(entry_dir, sizeof(entry_dir), "%s/%s", voicemail->root, entry->d_name) >= (int)sizeof(entry_dir)) {
            continue;
        }
        if (!path_is_directory(entry_dir)) {
            continue;
        }
        voicemail_add_watch(voicemail, entry_dir, 0);
    }
    closedir(root_dir);
}

static void voicemail_refresh_watches(struct voicemail_runtime *voicemail)
{
    char candidate[C300X_MAX_PATH_LEN];
    int root_available;

    if (voicemail->inotify_fd < 0) {
        return;
    }
    voicemail_clear_watches(voicemail);
    root_available = path_is_directory(voicemail->root);
    if (root_available) {
        voicemail_add_watch(voicemail, voicemail->root, 1);
    } else if (snprintf(candidate, sizeof(candidate), "%s", voicemail->root) < (int)sizeof(candidate)) {
        while (path_parent_inplace(candidate)) {
            if (path_is_directory(candidate)) {
                voicemail_add_watch(voicemail, candidate, 1);
                break;
            }
        }
    }
    if (!voicemail->watch_enabled || !root_available) {
        return;
    }
    voicemail_add_entry_dir_watches(voicemail);
    drain_inotify_events(voicemail->inotify_fd);
}

static void voicemail_close(struct voicemail_runtime *voicemail)
{
    if (voicemail->inotify_fd < 0) {
        return;
    }
    voicemail_clear_watches(voicemail);
    close(voicemail->inotify_fd);
    voicemail->inotify_fd = -1;
}

static void voicemail_runtime_init(
    struct voicemail_runtime *voicemail,
    int enabled,
    int watch_enabled,
    int max_messages,
    const char *root
)
{
    struct voicemail_snapshot *snapshot;

    memset(voicemail, 0, sizeof(*voicemail));
    voicemail->enabled = enabled;
    voicemail->watch_enabled = watch_enabled;
    voicemail->max_messages = max_messages;
    if (voicemail->max_messages <= 0 || voicemail->max_messages > C300X_MAX_VOICEMAIL_MESSAGES) {
        voicemail->max_messages = C300X_MAX_VOICEMAIL_MESSAGES;
    }
    snprintf(voicemail->root, sizeof(voicemail->root), "%s", root != NULL ? root : "");
    voicemail->inotify_fd = -1;

    snapshot = calloc(1, sizeof(*snapshot));
    if (snapshot != NULL) {
        voicemail_read_snapshot(voicemail, snapshot);
        voicemail->last_signature = voicemail_signature(snapshot);
        free(snapshot);
    }
    if (!voicemail->enabled || !voicemail->watch_enabled) {
        return;
    }
#ifdef IN_CLOEXEC
    voicemail->inotify_fd = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
#else
    voicemail->inotify_fd = inotify_init();
#endif
    if (voicemail->inotify_fd < 0) {
        return;
    }
#ifndef IN_CLOEXEC
    set_fd_nonblocking(voicemail->inotify_fd);
#endif
    voicemail_refresh_watches(voicemail);
}

static void voicemail_init(struct agent_runtime *runtime, const struct c300x_config *config)
{
    voicemail_runtime_init(
        &runtime->voicemail,
        config->answering_machine_messages_enabled,
        config->answering_machine_messages_watch,
        config->answering_machine_messages_max,
        config->answering_machine_messages_root
    );
}

static unsigned long long memos_signature_for_snapshots(
    const struct voicemail_snapshot *text,
    const struct voicemail_snapshot *voice
)
{
    unsigned long long hash = voicemail_signature(text);

    hash = signature_hash_bytes(hash, &voice->available, sizeof(voice->available));
    hash = signature_hash_bytes(hash, &voice->total, sizeof(voice->total));
    hash = signature_hash_bytes(hash, &voice->unread, sizeof(voice->unread));
    hash = signature_hash_bytes(hash, &voice->read, sizeof(voice->read));
    hash = signature_hash_bytes(hash, voice->newest_at, strlen(voice->newest_at));
    for (int index = 0; index < voice->message_count; index++) {
        const struct voicemail_message *message = &voice->messages[index];
        hash = signature_hash_bytes(hash, message->id, strlen(message->id));
        hash = signature_hash_bytes(hash, &message->read, sizeof(message->read));
        hash = signature_hash_bytes(hash, &message->unix_time, sizeof(message->unix_time));
    }
    return hash;
}

static unsigned long long memos_signature(struct agent_runtime *runtime)
{
    struct voicemail_snapshot *text = calloc(1, sizeof(*text));
    struct voicemail_snapshot *voice = calloc(1, sizeof(*voice));
    unsigned long long hash = 0;

    if (text != NULL && voice != NULL) {
        message_collection_read_snapshot(&runtime->text_memos, "text", text);
        message_collection_read_snapshot(&runtime->voice_memos, "voice", voice);
        hash = memos_signature_for_snapshots(text, voice);
    }
    free(text);
    free(voice);
    return hash;
}

static void memos_init(struct agent_runtime *runtime, const struct c300x_config *config)
{
    voicemail_runtime_init(
        &runtime->text_memos,
        config->memos_enabled,
        config->memos_watch,
        config->memos_max,
        config->memos_text_root
    );
    voicemail_runtime_init(
        &runtime->voice_memos,
        config->memos_enabled,
        config->memos_watch,
        config->memos_max,
        config->memos_voice_root
    );
    runtime->memos_last_signature = memos_signature(runtime);
}

static size_t json_escape_string(const char *value, char *out, size_t out_len)
{
    size_t used = 0;
    if (out_len == 0) {
        return 0;
    }
    for (size_t index = 0; value[index] != '\0' && used + 1 < out_len; index++) {
        unsigned char ch = (unsigned char)value[index];
        if (ch == '\\' || ch == '"') {
            if (used + 2 >= out_len) {
                break;
            }
            out[used++] = '\\';
            out[used++] = (char)ch;
            continue;
        }
        if (ch < 0x20) {
            if (used + 6 >= out_len) {
                break;
            }
            used += (size_t)snprintf(out + used, out_len - used, "\\u%04x", ch);
            continue;
        }
        out[used++] = (char)ch;
    }
    out[used] = '\0';
    return used;
}

static const char *json_string(const char *value, char *out, size_t out_len)
{
    size_t used;
    if (out_len < 3) {
        return "\"\"";
    }
    out[0] = '"';
    used = json_escape_string(value != NULL ? value : "", out + 1, out_len - 2);
    out[used + 1] = '"';
    out[used + 2] = '\0';
    return out;
}

static const char *json_string_or_null(const char *value, char *out, size_t out_len)
{
    if (value == NULL || value[0] == '\0') {
        return "null";
    }
    return json_string(value, out, out_len);
}

static int appendf(char *buffer, size_t buffer_len, size_t *used, const char *fmt, ...)
{
    va_list args;
    int written;
    if (*used >= buffer_len) {
        return 0;
    }
    va_start(args, fmt);
    written = vsnprintf(buffer + *used, buffer_len - *used, fmt, args);
    va_end(args);
    if (written < 0) {
        return 0;
    }
    if ((size_t)written >= buffer_len - *used) {
        *used = buffer_len;
        return 0;
    }
    *used += (size_t)written;
    return 1;
}

static char *allocate_response_buffer(int client_fd, size_t size)
{
    char *buffer = calloc(1, size);

    if (buffer == NULL) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
    }
    return buffer;
}

static void ui_event_send(int client_fd, int changed, unsigned long revision, const char *topic)
{
    char body[192];
    char escaped_topic[96];
    char quoted_topic[100];
    const char *topic_json = "null";

    if (topic != NULL && topic[0] != '\0') {
        json_escape_string(topic, escaped_topic, sizeof(escaped_topic));
        snprintf(quoted_topic, sizeof(quoted_topic), "\"%s\"", escaped_topic);
        topic_json = quoted_topic;
    }
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"changed\":%s,\"revision\":%lu,\"topic\":%s}\n",
        changed ? "true" : "false",
        revision,
        topic_json
    );
    send_json(client_fd, 200, "OK", body);
}

static void ui_event_close_wait(struct agent_runtime *runtime, int changed)
{
    int fd = runtime->ui_event_wait_fd;

    if (fd < 0) {
        return;
    }
    runtime->ui_event_wait_fd = -1;
    ui_event_send(fd, changed, runtime->ui_event_revision, runtime->ui_event_topic);
    close(fd);
}

static void ui_event_notify(struct agent_runtime *runtime, const char *topic)
{
    runtime->ui_event_revision++;
    snprintf(runtime->ui_event_topic, sizeof(runtime->ui_event_topic), "%s", topic != NULL ? topic : "");
    if (runtime->ui_event_wait_fd >= 0 && runtime->ui_event_revision > runtime->ui_event_wait_since) {
        ui_event_close_wait(runtime, 1);
    }
}

static int ui_event_timeout_ms(const struct agent_runtime *runtime, time_t now)
{
    if (runtime->ui_event_wait_fd < 0) {
        return -1;
    }
    return timeout_until_ms(now, runtime->ui_event_wait_deadline);
}

static void ui_event_expire_wait(struct agent_runtime *runtime, time_t now)
{
    if (runtime->ui_event_wait_fd >= 0 && runtime->ui_event_wait_deadline <= now) {
        ui_event_close_wait(runtime, 0);
    }
}

static void handle_ui_events_status(int client_fd, const struct agent_runtime *runtime)
{
    char body[96];

    snprintf(body, sizeof(body), "{\"ok\":true,\"revision\":%lu}\n", runtime->ui_event_revision);
    send_json(client_fd, 200, "OK", body);
}

static int handle_ui_events_next(
    int client_fd,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    char since_text[32];
    char *end = NULL;
    unsigned long since = 0;

    if (
        query_param_value(request->query, "since", since_text, sizeof(since_text))
        && since_text[0] != '\0'
    ) {
        errno = 0;
        since = strtoul(since_text, &end, 10);
        if (errno != 0 || end == since_text || (end != NULL && *end != '\0')) {
            send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_revision\"}\n");
            return 1;
        }
    }
    if (since < runtime->ui_event_revision) {
        ui_event_send(client_fd, 1, runtime->ui_event_revision, runtime->ui_event_topic);
        return 1;
    }
    if (runtime->ui_event_wait_fd >= 0) {
        ui_event_close_wait(runtime, 0);
    }
    runtime->ui_event_wait_fd = client_fd;
    runtime->ui_event_wait_since = since;
    runtime->ui_event_wait_deadline = time(NULL) + 300;
    return 0;
}

static void voicemail_event_dispatch_snapshot(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    int force
)
{
    struct voicemail_snapshot *snapshot = calloc(1, sizeof(*snapshot));
    unsigned long long signature;
    char data[512];
    char newest_at_escaped[96];
    char newest_at_quoted[100];
    const char *newest_at_json = "null";

    if (snapshot == NULL) {
        return;
    }
    voicemail_read_snapshot(&runtime->voicemail, snapshot);
    signature = voicemail_signature(snapshot);
    if (!force && signature == runtime->voicemail.last_signature) {
        free(snapshot);
        return;
    }
    runtime->voicemail.last_signature = signature;
    if (snapshot->newest_at[0] != '\0') {
        json_escape_string(snapshot->newest_at, newest_at_escaped, sizeof(newest_at_escaped));
        snprintf(newest_at_quoted, sizeof(newest_at_quoted), "\"%s\"", newest_at_escaped);
        newest_at_json = newest_at_quoted;
    }
    snprintf(
        data,
        sizeof(data),
        "{\"voicemail\":{\"available\":%s,\"total\":%d,\"unread\":%d,\"read\":%d,\"newest_at\":%s}}",
        snapshot->available ? "true" : "false",
        snapshot->total,
        snapshot->unread,
        snapshot->read,
        newest_at_json
    );
    free(snapshot);
    ui_event_notify(runtime, "answering_machine.messages");
    dispatch_event(config, runtime, "answering_machine.messages_changed", data, 30);
}

static void voicemail_event_dispatch_if_changed(
    const struct c300x_config *config,
    struct agent_runtime *runtime
)
{
    voicemail_event_dispatch_snapshot(config, runtime, 0);
}

static const char *newest_memo_time(
    const struct voicemail_snapshot *text,
    const struct voicemail_snapshot *voice
)
{
    long long text_timestamp = text->message_count > 0 ? text->messages[0].timestamp : 0;
    long long voice_timestamp = voice->message_count > 0 ? voice->messages[0].timestamp : 0;
    if (voice_timestamp > text_timestamp) {
        return voice->newest_at;
    }
    return text->newest_at;
}

static void memos_event_dispatch_snapshot(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    int force
)
{
    struct voicemail_snapshot *text = calloc(1, sizeof(*text));
    struct voicemail_snapshot *voice = calloc(1, sizeof(*voice));
    unsigned long long signature;
    char data[2048];
    char newest_at_escaped[96];
    char newest_at_quoted[100];
    const char *newest_at_json = "null";
    const char *newest_at;

    if (text == NULL || voice == NULL) {
        free(text);
        free(voice);
        return;
    }
    message_collection_read_snapshot(&runtime->text_memos, "text", text);
    message_collection_read_snapshot(&runtime->voice_memos, "voice", voice);
    signature = memos_signature_for_snapshots(text, voice);
    if (!force && signature == runtime->memos_last_signature) {
        free(text);
        free(voice);
        return;
    }
    runtime->memos_last_signature = signature;

    newest_at = newest_memo_time(text, voice);
    if (newest_at[0] != '\0') {
        json_escape_string(newest_at, newest_at_escaped, sizeof(newest_at_escaped));
        snprintf(newest_at_quoted, sizeof(newest_at_quoted), "\"%s\"", newest_at_escaped);
        newest_at_json = newest_at_quoted;
    }
    snprintf(
        data,
        sizeof(data),
        "{\"memos\":{\"available\":%s,\"total\":%d,\"text_total\":%d,\"voice_total\":%d,\"unread\":%d,\"read\":%d,\"newest_at\":%s}}",
        (text->available || voice->available) ? "true" : "false",
        text->total + voice->total,
        text->total,
        voice->total,
        text->unread + voice->unread,
        text->read + voice->read,
        newest_at_json
    );
    free(text);
    free(voice);
    ui_event_notify(runtime, "memos");
    dispatch_event(config, runtime, "memos.changed", data, 30);
}

static void memos_event_dispatch_if_changed(
    const struct c300x_config *config,
    struct agent_runtime *runtime
)
{
    memos_event_dispatch_snapshot(config, runtime, 0);
}

static void handle_memos_inotify(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    struct voicemail_runtime *memos
)
{
    int structure_changed = 0;

    if (memos->inotify_fd < 0) {
        return;
    }
    if (!read_inotify_change_events(memos->inotify_fd, &structure_changed)) {
        return;
    }
    if (structure_changed) {
        voicemail_refresh_watches(memos);
    }
    memos_event_dispatch_if_changed(config, runtime);
}

static void handle_voicemail_inotify(
    const struct c300x_config *config,
    struct agent_runtime *runtime
)
{
    int structure_changed = 0;

    if (runtime->voicemail.inotify_fd < 0) {
        return;
    }
    if (!read_inotify_change_events(runtime->voicemail.inotify_fd, &structure_changed)) {
        return;
    }
    if (structure_changed) {
        voicemail_refresh_watches(&runtime->voicemail);
    }
    voicemail_event_dispatch_if_changed(config, runtime);
}

static void utc_now(char *out, size_t out_len)
{
    time_t now = time(NULL);
    struct tm tm_value;

    gmtime_r(&now, &tm_value);
    strftime(out, out_len, "%Y-%m-%dT%H:%M:%SZ", &tm_value);
}

static void json_string_field_range(
    const char *start,
    const char *end,
    const char *field,
    char *out,
    size_t out_len
)
{
    char pattern[64];
    const char *found;
    const char *ptr;
    size_t written = 0;

    if (out_len > 0) {
        out[0] = '\0';
    }
    snprintf(pattern, sizeof(pattern), "\"%s\"", field);
    found = start;
    while (found != NULL && found < end) {
        found = strstr(found, pattern);
        if (found == NULL || found >= end) {
            return;
        }
        ptr = found + strlen(pattern);
        while (ptr < end && isspace((unsigned char)*ptr)) {
            ptr++;
        }
        if (ptr < end && *ptr == ':') {
            break;
        }
        found++;
    }
    if (found == NULL || found >= end) {
        return;
    }
    ptr = strchr(found + strlen(pattern), ':');
    if (ptr == NULL || ptr >= end) {
        return;
    }
    ptr++;
    while (ptr < end && isspace((unsigned char)*ptr)) {
        ptr++;
    }
    if (ptr >= end || *ptr != '"') {
        return;
    }
    ptr++;
    while (ptr < end && *ptr != '"' && written + 1 < out_len) {
        if (*ptr == '\\' && ptr + 1 < end) {
            ptr++;
        }
        out[written++] = *ptr++;
    }
    if (out_len > 0) {
        out[written] = '\0';
    }
}

static void json_events_array_range(
    const char *start,
    const char *end,
    struct subscription *subscription
)
{
    const char *found = strstr(start, "\"events\"");
    const char *ptr;

    subscription->event_count = 0;
    if (found == NULL || found >= end) {
        return;
    }
    ptr = strchr(found, '[');
    if (ptr == NULL || ptr >= end) {
        return;
    }
    ptr++;
    while (ptr < end && subscription->event_count < C300X_MAX_SUBSCRIPTION_EVENTS) {
        size_t written = 0;
        while (ptr < end && *ptr != '"' && *ptr != ']') {
            ptr++;
        }
        if (ptr >= end || *ptr == ']') {
            return;
        }
        ptr++;
        while (ptr < end && *ptr != '"' && written + 1 < sizeof(subscription->events[0])) {
            if (*ptr == '\\' && ptr + 1 < end) {
                ptr++;
            }
            subscription->events[subscription->event_count][written++] = *ptr++;
        }
        subscription->events[subscription->event_count][written] = '\0';
        if (written > 0 && validate_event_name(subscription->events[subscription->event_count])) {
            subscription->event_count++;
        }
        while (ptr < end && *ptr != ',' && *ptr != ']') {
            ptr++;
        }
        if (ptr < end && *ptr == ',') {
            ptr++;
        }
    }
}

static int subscription_matches_event(const struct subscription *subscription, const char *event_type)
{
    if (subscription->event_count == 0) {
        return 0;
    }
    for (int index = 0; index < subscription->event_count; index++) {
        if (strcmp(subscription->events[index], event_type) == 0) {
            return 1;
        }
    }
    return 0;
}

static int subscription_events_equal(const struct subscription *left, const struct subscription *right)
{
    if (left->event_count != right->event_count) {
        return 0;
    }
    for (int left_index = 0; left_index < left->event_count; left_index++) {
        int found = 0;
        for (int right_index = 0; right_index < right->event_count; right_index++) {
            if (strcmp(left->events[left_index], right->events[right_index]) == 0) {
                found = 1;
                break;
            }
        }
        if (!found) {
            return 0;
        }
    }
    return 1;
}

static int subscription_equals(const struct subscription *left, const struct subscription *right)
{
    return strcmp(left->callback_url, right->callback_url) == 0
        && strcmp(left->token, right->token) == 0
        && subscription_events_equal(left, right);
}

static void dispatch_subscription_snapshots(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct subscription *subscription
)
{
    if (subscription_matches_event(subscription, "answering_machine.messages_changed")) {
        voicemail_event_dispatch_snapshot(config, runtime, 1);
    }
    if (subscription_matches_event(subscription, "memos.changed")) {
        memos_event_dispatch_snapshot(config, runtime, 1);
    }
}

static void subscription_token_fingerprint(
    const char *token,
    char *output,
    size_t output_len
)
{
    fnv1a64_fingerprint(token, output, output_len);
}

static void load_subscriptions(struct agent_runtime *runtime, const char *store_path)
{
    FILE *file;
    long size;
    char *buffer;
    const char *ptr;

    runtime->subscription_count = 0;
    if (store_path[0] == '\0') {
        return;
    }
    file = fopen(store_path, "rb");
    if (file == NULL) {
        return;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return;
    }
    size = ftell(file);
    if (size <= 0 || size > 1024 * 1024) {
        fclose(file);
        return;
    }
    if (fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return;
    }
    buffer = calloc((size_t)size + 1, 1);
    if (buffer == NULL) {
        fclose(file);
        return;
    }
    if (fread(buffer, 1, (size_t)size, file) != (size_t)size) {
        free(buffer);
        fclose(file);
        return;
    }
    fclose(file);

    ptr = buffer;
    while (1) {
        const char *callback = strstr(ptr, "\"callback_url\"");
        const char *object_start;
        const char *object_end;
        struct subscription subscription;

        if (callback == NULL) {
            break;
        }
        object_start = callback;
        while (object_start > buffer && *object_start != '{') {
            object_start--;
        }
        object_end = strchr(callback, '}');
        if (object_start == buffer && *object_start != '{') {
            break;
        }
        if (object_end == NULL) {
            break;
        }
        memset(&subscription, 0, sizeof(subscription));
        json_string_field_range(object_start, object_end, "id", subscription.id, sizeof(subscription.id));
        json_string_field_range(
            object_start,
            object_end,
            "callback_url",
            subscription.callback_url,
            sizeof(subscription.callback_url)
        );
        json_string_field_range(object_start, object_end, "token", subscription.token, sizeof(subscription.token));
        json_events_array_range(object_start, object_end, &subscription);
        if (subscription.callback_url[0] != '\0') {
            if (subscription.id[0] == '\0') {
                snprintf(subscription.id, sizeof(subscription.id), "native-%ld-0", (long)time(NULL));
            }
            if (runtime->subscription_count > 0) {
                runtime->subscriptions_loaded_deduplicated = 1;
            }
            runtime->subscriptions[0] = subscription;
            runtime->subscription_count = 1;
        }
        ptr = object_end + 1;
    }
    free(buffer);
}

static void save_subscriptions(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const char *store_path,
    const char *reason
)
{
    char temporary_path[C300X_MAX_PATH_LEN + 8];
    FILE *file;

    if (store_path[0] == '\0') {
        return;
    }
    snprintf(temporary_path, sizeof(temporary_path), "%s.tmp", store_path);
    file = fopen(temporary_path, "w");
    if (file == NULL) {
        return;
    }
    fprintf(file, "{\n  \"subscriptions\": [\n");
    for (int index = 0; index < runtime->subscription_count; index++) {
        const struct subscription *subscription = &runtime->subscriptions[index];
        char id[C300X_JSON_QUOTED_LEN(sizeof(subscription->id))];
        char callback_url[C300X_JSON_QUOTED_LEN(sizeof(subscription->callback_url))];
        char token[C300X_JSON_QUOTED_LEN(sizeof(subscription->token))];
        char last_event_type[C300X_JSON_QUOTED_LEN(sizeof(subscription->last_event_type))];
        char last_delivered_at[C300X_JSON_QUOTED_LEN(sizeof(subscription->last_delivered_at))];

        json_string(subscription->id, id, sizeof(id));
        json_string(subscription->callback_url, callback_url, sizeof(callback_url));
        json_string(subscription->token, token, sizeof(token));
        json_string(subscription->last_event_type, last_event_type, sizeof(last_event_type));
        json_string(subscription->last_delivered_at, last_delivered_at, sizeof(last_delivered_at));
        fprintf(
            file,
            "    {\"id\":%s,\"callback_url\":%s,\"token\":%s,\"events\":[",
            id,
            callback_url,
            token
        );
        for (int event_index = 0; event_index < subscription->event_count; event_index++) {
            char event_type[C300X_JSON_QUOTED_LEN(sizeof(subscription->events[0]))];
            json_string(subscription->events[event_index], event_type, sizeof(event_type));
            fprintf(file, "%s%s", event_index == 0 ? "" : ",", event_type);
        }
        fprintf(
            file,
            "],\"created_at\":\"\",\"last_delivery\":{\"ok\":%s,\"event_type\":%s,\"delivered_at\":%s}}%s\n",
            subscription->last_ok ? "true" : "false",
            last_event_type,
            last_delivered_at,
            index + 1 == runtime->subscription_count ? "" : ","
        );
    }
    fprintf(file, "  ]\n}\n");
    fclose(file);
    (void)chmod(temporary_path, 0600);
    if (rename(temporary_path, store_path) == 0) {
        (void)chmod(store_path, 0600);
        record_agent_write(config, runtime, "subscription", reason);
    } else {
        (void)unlink(temporary_path);
    }
}

static void record_recent_event(struct agent_runtime *runtime, const char *event_json)
{
    size_t event_len = strlen(event_json);

    if (runtime->recent_count < C300X_MAX_RECENT_EVENTS) {
        if (event_len < sizeof(runtime->recent_events[0])) {
            memcpy(runtime->recent_events[runtime->recent_count], event_json, event_len + 1);
        } else {
            snprintf(
                runtime->recent_events[runtime->recent_count],
                sizeof(runtime->recent_events[0]),
                "{\"type\":\"diagnostic.recent_event_truncated\",\"data\":{\"size\":%zu}}",
                event_len
            );
        }
        runtime->recent_count++;
        return;
    }
    for (int index = 1; index < C300X_MAX_RECENT_EVENTS; index++) {
        memcpy(runtime->recent_events[index - 1], runtime->recent_events[index], sizeof(runtime->recent_events[0]));
    }
    if (event_len < sizeof(runtime->recent_events[0])) {
        memcpy(runtime->recent_events[C300X_MAX_RECENT_EVENTS - 1], event_json, event_len + 1);
    } else {
        snprintf(
            runtime->recent_events[C300X_MAX_RECENT_EVENTS - 1],
            sizeof(runtime->recent_events[0]),
            "{\"type\":\"diagnostic.recent_event_truncated\",\"data\":{\"size\":%zu}}",
            event_len
        );
    }
}

static int parse_http_url(const char *url, char *host, size_t host_len, char *port, size_t port_len, char *path, size_t path_len)
{
    const char *ptr;
    const char *host_start;
    const char *host_end;
    const char *path_start;
    const char *colon;
    const char *bracket_end;

    if (strncmp(url, "http://", 7) != 0) {
        return 0;
    }
    host_start = url + 7;
    path_start = strchr(host_start, '/');
    if (path_start == NULL) {
        path_start = url + strlen(url);
    }
    colon = NULL;
    if (*host_start == '[') {
        bracket_end = memchr(host_start, ']', (size_t)(path_start - host_start));
        if (bracket_end == NULL || bracket_end == host_start + 1) {
            return 0;
        }
        if (bracket_end + 1 < path_start) {
            if (bracket_end[1] != ':') {
                return 0;
            }
            colon = bracket_end + 1;
        }
        host_start++;
        host_end = bracket_end;
    } else {
        for (ptr = host_start; ptr < path_start; ptr++) {
            if (*ptr == ':') {
                colon = ptr;
                break;
            }
        }
        host_end = colon != NULL ? colon : path_start;
    }
    if (host_end == host_start || (size_t)(host_end - host_start) >= host_len) {
        return 0;
    }
    memcpy(host, host_start, (size_t)(host_end - host_start));
    host[host_end - host_start] = '\0';
    if (colon != NULL) {
        size_t len = (size_t)(path_start - colon - 1);
        if (len == 0 || len >= port_len) {
            return 0;
        }
        memcpy(port, colon + 1, len);
        port[len] = '\0';
    } else {
        snprintf(port, port_len, "80");
    }
    if (*path_start == '\0') {
        snprintf(path, path_len, "/");
    } else {
        snprintf(path, path_len, "%s", path_start);
    }
    return 1;
}

static void http_host_header_value(
    const char *host,
    const char *port,
    char *out,
    size_t out_len
)
{
    int is_ipv6_literal = strchr(host, ':') != NULL;
    int default_port = strcmp(port, "80") == 0;

    if (is_ipv6_literal) {
        if (default_port) {
            snprintf(out, out_len, "[%s]", host);
        } else {
            snprintf(out, out_len, "[%s]:%s", host, port);
        }
    } else if (default_port) {
        snprintf(out, out_len, "%s", host);
    } else {
        snprintf(out, out_len, "%s:%s", host, port);
    }
}

static int post_callback(
    const struct c300x_config *config,
    const struct subscription *subscription,
    const char *event_json
)
{
    char host[256];
    char host_header[288];
    char port[16];
    char path[256];
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    struct addrinfo *item;
    int fd = -1;
    char header[1024];
    char response[64];
    int ok = 0;

    if (!parse_http_url(subscription->callback_url, host, sizeof(host), port, sizeof(port), path, sizeof(path))) {
        return 0;
    }
    memset(&hints, 0, sizeof(hints));
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_family = AF_UNSPEC;
    if (getaddrinfo(host, port, &hints, &result) != 0) {
        return 0;
    }
    http_host_header_value(host, port, host_header, sizeof(host_header));
    for (item = result; item != NULL; item = item->ai_next) {
        fd = socket(item->ai_family, item->ai_socktype, item->ai_protocol);
        if (fd < 0) {
            continue;
        }
        set_fd_cloexec(fd);
        set_socket_timeout(fd, config->callback_timeout_ms);
        if (connect(fd, item->ai_addr, item->ai_addrlen) == 0) {
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(result);
    if (fd < 0) {
        return 0;
    }
    snprintf(
        header,
        sizeof(header),
        "POST %s HTTP/1.1\r\n"
        "Host: %s\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %zu\r\n"
        "%s%s%s"
        "Connection: close\r\n"
        "\r\n",
        path,
        host_header,
        strlen(event_json),
        subscription->token[0] != '\0' ? C300X_EVENT_TOKEN_HEADER ": " : "",
        subscription->token[0] != '\0' ? subscription->token : "",
        subscription->token[0] != '\0' ? "\r\n" : ""
    );
    if (send(fd, header, strlen(header), MSG_NOSIGNAL) > 0
        && send(fd, event_json, strlen(event_json), MSG_NOSIGNAL) > 0
        && recv(fd, response, sizeof(response) - 1, 0) > 0) {
        response[sizeof(response) - 1] = '\0';
        ok = strncmp(response, "HTTP/1.1 2", 10) == 0 || strncmp(response, "HTTP/1.0 2", 10) == 0;
    }
    close(fd);
    return ok;
}

static void handle_subscriptions_get(int client_fd, const struct agent_runtime *runtime)
{
    char body[8192];
    size_t used = 0;

    if (!appendf(body, sizeof(body), &used, "{\"ok\":true,\"subscriptions\":[")) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        return;
    }
    for (int index = 0; index < runtime->subscription_count && used < sizeof(body); index++) {
        const struct subscription *subscription = &runtime->subscriptions[index];
        char id[C300X_JSON_QUOTED_LEN(sizeof(subscription->id))];
        char callback_url[C300X_JSON_QUOTED_LEN(sizeof(subscription->callback_url))];
        char token_fingerprint[C300X_TOKEN_FINGERPRINT_LEN];
        char token_fingerprint_json[C300X_JSON_QUOTED_LEN(C300X_TOKEN_FINGERPRINT_LEN)];
        char last_event_type[C300X_JSON_QUOTED_LEN(sizeof(subscription->last_event_type))];
        char last_delivered_at[C300X_JSON_QUOTED_LEN(sizeof(subscription->last_delivered_at))];

        subscription_token_fingerprint(subscription->token, token_fingerprint, sizeof(token_fingerprint));
        json_string(subscription->id, id, sizeof(id));
        json_string(subscription->callback_url, callback_url, sizeof(callback_url));
        json_string(token_fingerprint, token_fingerprint_json, sizeof(token_fingerprint_json));
        json_string(subscription->last_event_type, last_event_type, sizeof(last_event_type));
        json_string(subscription->last_delivered_at, last_delivered_at, sizeof(last_delivered_at));
        if (!appendf(
            body,
            sizeof(body),
            &used,
            "%s{\"id\":%s,\"callback_url\":%s,\"token_fingerprint\":%s,\"events\":[",
            index == 0 ? "" : ",",
            id,
            callback_url,
            token_fingerprint_json
        )) {
            send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
            return;
        }
        for (int event_index = 0; event_index < subscription->event_count && used < sizeof(body); event_index++) {
            char event_type[C300X_JSON_QUOTED_LEN(sizeof(subscription->events[0]))];
            json_string(subscription->events[event_index], event_type, sizeof(event_type));
            if (!appendf(
                body,
                sizeof(body),
                &used,
                "%s%s",
                event_index == 0 ? "" : ",",
                event_type
            )) {
                send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
                return;
            }
        }
        if (!appendf(
            body,
            sizeof(body),
            &used,
            "],\"last_delivery\":{\"ok\":%s,\"event_type\":%s,\"delivered_at\":%s}}",
            subscription->last_ok ? "true" : "false",
            last_event_type,
            last_delivered_at
        )) {
            send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
            return;
        }
    }
    if (!appendf(body, sizeof(body), &used, "]}\n")) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        return;
    }
    send_json(client_fd, 200, "OK", body);
}

static void handle_recent_events_get(int client_fd, const struct agent_runtime *runtime)
{
    char *body = allocate_response_buffer(client_fd, C300X_LARGE_RESPONSE_SIZE);
    size_t used = 0;

    if (body == NULL) {
        return;
    }
    if (!appendf(body, C300X_LARGE_RESPONSE_SIZE, &used, "{\"ok\":true,\"events\":[")) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        free(body);
        return;
    }
    for (int index = 0; index < runtime->recent_count; index++) {
        if (!appendf(
            body,
            C300X_LARGE_RESPONSE_SIZE,
            &used,
            "%s%s",
            index == 0 ? "" : ",",
            runtime->recent_events[index]
        )) {
            send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
            free(body);
            return;
        }
    }
    if (!appendf(body, C300X_LARGE_RESPONSE_SIZE, &used, "]}\n")) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        free(body);
        return;
    }
    send_json(client_fd, 200, "OK", body);
    free(body);
}

static void handle_subscriptions_post(
    int client_fd,
    struct agent_runtime *runtime,
    const struct c300x_config *config,
    const struct request *request
)
{
    struct subscription subscription;
    char body[1024];
    char subscription_id_json[C300X_JSON_QUOTED_LEN(sizeof(subscription.id))];
    int matching_index = -1;
    int had_existing;

    memset(&subscription, 0, sizeof(subscription));
    json_string_field(request->body, "callback_url", subscription.callback_url, sizeof(subscription.callback_url));
    json_string_field(request->body, "token", subscription.token, sizeof(subscription.token));
    json_events_array_range(request->body, request->body + strlen(request->body), &subscription);
    if (subscription.callback_url[0] == '\0') {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"callback_url_required\"}\n");
        return;
    }
    if (strncmp(subscription.callback_url, "http://", 7) != 0) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"unsupported_callback_url\"}\n");
        return;
    }
    if (subscription.event_count == 0) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"events_required\"}\n");
        return;
    }
    had_existing = runtime->subscription_count > 0;
    for (int index = 0; index < runtime->subscription_count; index++) {
        if (subscription_equals(&runtime->subscriptions[index], &subscription)) {
            matching_index = index;
            break;
        }
    }
    if (matching_index >= 0) {
        snprintf(subscription.id, sizeof(subscription.id), "%s", runtime->subscriptions[matching_index].id);
        if (runtime->subscription_count == 1) {
            if (runtime->subscriptions_loaded_deduplicated) {
                save_subscriptions(config, runtime, config->subscription_store_path, "deduplicated");
                runtime->subscriptions_loaded_deduplicated = 0;
            }
            json_string(runtime->subscriptions[0].id, subscription_id_json, sizeof(subscription_id_json));
            snprintf(body, sizeof(body), "{\"ok\":true,\"subscription\":{\"id\":%s}}\n", subscription_id_json);
            if (subscription_matches_event(&runtime->subscriptions[0], "system.metrics_changed")) {
                system_metrics_dispatch_now(config, runtime, time(NULL));
            }
            dispatch_subscription_snapshots(config, runtime, &runtime->subscriptions[0]);
            send_json(client_fd, 200, "OK", body);
            return;
        }
    }

    if (subscription.id[0] == '\0') {
        if (had_existing && runtime->subscriptions[0].id[0] != '\0') {
            snprintf(subscription.id, sizeof(subscription.id), "%s", runtime->subscriptions[0].id);
        } else {
            snprintf(subscription.id, sizeof(subscription.id), "native-%ld-0", (long)time(NULL));
        }
    }

    runtime->subscriptions[0] = subscription;
    runtime->subscription_count = 1;
    save_subscriptions(
        config,
        runtime,
        config->subscription_store_path,
        matching_index >= 0 ? "deduplicated" : (had_existing ? "replaced" : "created")
    );
    json_string(runtime->subscriptions[0].id, subscription_id_json, sizeof(subscription_id_json));
    snprintf(body, sizeof(body), "{\"ok\":true,\"subscription\":{\"id\":%s}}\n", subscription_id_json);
    if (subscription_matches_event(&runtime->subscriptions[0], "system.metrics_changed")) {
        system_metrics_dispatch_now(config, runtime, time(NULL));
    }
    dispatch_subscription_snapshots(config, runtime, &runtime->subscriptions[0]);
    send_json(client_fd, 201, "Created", body);
}

static void handle_display_bridge_status(
    int client_fd,
    const struct c300x_config *config,
    const struct agent_runtime *runtime
)
{
    char body[384];
    char callback_hash[C300X_TOKEN_FINGERPRINT_LEN];
    int active = display_bridge_active(config, runtime);

    display_bridge_callback_fingerprint(
        active,
        display_bridge_webhook_url(config, runtime),
        display_bridge_shared_secret(config, runtime),
        callback_hash,
        sizeof(callback_hash)
    );
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"enabled\":%s,\"configured\":%s,\"display_bridge_configured\":%s,\"callback_hash\":\"%s\",\"source\":\"%s\"}\n",
        active ? "true" : "false",
        active ? "true" : "false",
        active ? "true" : "false",
        callback_hash,
        (display_bridge_runtime_active(runtime) || display_bridge_runtime_disabled(runtime)) ? "runtime" : "config"
    );
    send_json(client_fd, 200, "OK", body);
}

static void handle_display_bridge_post(
    int client_fd,
    struct agent_runtime *runtime,
    const struct c300x_config *config,
    const struct request *request
)
{
    int enabled = 1;
    char webhook_url[C300X_MAX_URL_LEN];
    char shared_secret[C300X_MAX_TOKEN_LEN];
    char host[256];
    char port[16];
    char path[256];
    (void)config;

    if (runtime == NULL) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"runtime_unavailable\"}\n");
        return;
    }
    (void)json_bool_field(request->body, "enabled", &enabled);
    if (!enabled) {
        if (!display_bridge_runtime_active(runtime) && !config->display_bridge_enabled && !runtime->display_bridge_disabled) {
            handle_display_bridge_status(client_fd, config, runtime);
            return;
        }
        runtime->display_bridge_registered = 0;
        runtime->display_bridge_disabled = 1;
        runtime->display_bridge_webhook_url[0] = '\0';
        runtime->display_bridge_shared_secret[0] = '\0';
        handle_display_bridge_status(client_fd, config, runtime);
        return;
    }

    json_string_field(request->body, "webhook_url", webhook_url, sizeof(webhook_url));
    json_string_field(request->body, "shared_secret", shared_secret, sizeof(shared_secret));
    if (webhook_url[0] == '\0') {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"webhook_url_required\"}\n");
        return;
    }
    if (shared_secret[0] == '\0') {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"shared_secret_required\"}\n");
        return;
    }
    if (strncmp(webhook_url, "http://", 7) != 0
        || !parse_http_url(webhook_url, host, sizeof(host), port, sizeof(port), path, sizeof(path))) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"unsupported_webhook_url\"}\n");
        return;
    }
    if (
        runtime->display_bridge_registered
        && !runtime->display_bridge_disabled
        && strcmp(runtime->display_bridge_webhook_url, webhook_url) == 0
        && strcmp(runtime->display_bridge_shared_secret, shared_secret) == 0
    ) {
        handle_display_bridge_status(client_fd, config, runtime);
        return;
    }
    snprintf(runtime->display_bridge_webhook_url, sizeof(runtime->display_bridge_webhook_url), "%s", webhook_url);
    snprintf(runtime->display_bridge_shared_secret, sizeof(runtime->display_bridge_shared_secret), "%s", shared_secret);
    runtime->display_bridge_registered = 1;
    runtime->display_bridge_disabled = 0;
    handle_display_bridge_status(client_fd, config, runtime);
}

static void handle_display_bridge_event_post(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    char topic[64];
    char topic_json[C300X_JSON_QUOTED_LEN(sizeof(topic))];
    char body[192];

    if (runtime == NULL) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"runtime_unavailable\"}\n");
        return;
    }
    if (!display_bridge_active(config, runtime)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"display_bridge_disabled\"}\n");
        return;
    }
    json_string_field(request->body, "topic", topic, sizeof(topic));
    if (!validate_event_name(topic)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_topic\"}\n");
        return;
    }

    mark_home_assistant_callback_seen(runtime, time(NULL));
    ui_event_notify(runtime, topic);
    json_string(topic, topic_json, sizeof(topic_json));
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"revision\":%lu,\"topic\":%s}\n",
        runtime->ui_event_revision,
        topic_json
    );
    send_json(client_fd, 202, "Accepted", body);
}

static void handle_diagnostics_get(int client_fd, const struct agent_runtime *runtime)
{
    char last_write_class[C300X_JSON_QUOTED_LEN(sizeof(runtime->last_write_class))];
    char last_write_reason[C300X_JSON_QUOTED_LEN(sizeof(runtime->last_write_reason))];
    char last_wake_reason[C300X_JSON_QUOTED_LEN(sizeof(runtime->last_wake_reason))];
    char qml_patch_last_action[C300X_JSON_QUOTED_LEN(sizeof(runtime->qml_patch_last_action))];
    struct c300x_video_status video_status;
    int open_fd_count = count_open_fds();
    char body[2048];

    json_string(runtime->last_write_class, last_write_class, sizeof(last_write_class));
    json_string(runtime->last_write_reason, last_write_reason, sizeof(last_write_reason));
    json_string(runtime->last_wake_reason, last_wake_reason, sizeof(last_wake_reason));
    json_string(runtime->qml_patch_last_action, qml_patch_last_action, sizeof(qml_patch_last_action));
    c300x_video_status(runtime->video, &video_status);
    if (
        snprintf(
            body,
            sizeof(body),
            "{"
            "\"ok\":true,"
            "\"agent_write_count\":%lu,"
            "\"last_write_at\":%ld,"
            "\"last_write_reason\":%s,"
            "\"last_write_class\":%s,"
            "\"subscription_store_writes\":%lu,"
            "\"qml_patch_last_action\":%s,"
            "\"loop_iterations\":%lu,"
            "\"poll_wakeups\":%lu,"
            "\"accepted_clients\":%lu,"
            "\"last_wake_reason\":%s,"
            "\"last_poll_timeout_ms\":%d,"
            "\"last_poll_count\":%d,"
            "\"open_fd_count\":%d,"
            "\"video_running\":%s,"
            "\"video_media_starting\":%s,"
            "\"video_call_active\":%s,"
            "\"video_clients\":%d,"
            "\"video_bridge_open_fds\":%d,"
            "\"video_bridge_active_threads\":%d"
            "}\n",
            runtime->agent_write_count,
            (long)runtime->last_write_at,
            last_write_reason,
            last_write_class,
            runtime->subscription_store_writes,
            qml_patch_last_action,
            runtime->loop_iterations,
            runtime->poll_wakeups,
            runtime->accepted_clients,
            last_wake_reason,
            runtime->last_poll_timeout_ms,
            runtime->last_poll_count,
            open_fd_count,
            video_status.running ? "true" : "false",
            video_status.media_starting ? "true" : "false",
            video_status.call_active ? "true" : "false",
            video_status.clients,
            video_status.bridge_open_fds,
            video_status.bridge_active_threads
        ) >= (int)sizeof(body)
    ) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        return;
    }
    send_json(client_fd, 200, "OK", body);
}

static void handle_setup_page(int client_fd)
{
    static const char header[] =
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        "\r\n";
    static const char *parts[] = {
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>C300X Agent Setup</title><style>body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:0}"
        "main{max-width:900px;margin:auto;padding:20px;min-width:0}section{border:1px solid #333;border-radius:8px;padding:14px;margin:0 0 14px;background:#181818;min-width:0}"
        "label{display:block;margin-top:8px;color:#bbb}input,select,textarea{box-sizing:border-box;width:100%;padding:7px;background:#0b0b0b;color:#eee;border:1px solid #444;border-radius:4px}"
        "button{margin:8px 8px 0 0;padding:8px 12px;border:0;border-radius:4px;background:#326de6;color:#fff}.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;min-width:0}"
        ".opt{display:grid;grid-template-columns:minmax(170px,220px) 1fr;gap:10px;align-items:start;margin-top:8px}.opt span{color:#ddd}.opt input{width:auto;margin-right:6px}.opt small{color:#9ca3af;line-height:1.35}"
        "pre{white-space:pre-wrap;background:#080808;border:1px solid #333;border-radius:4px;padding:10px;max-height:42vh;overflow:auto;overflow-wrap:anywhere;word-break:break-word;font-size:12px;line-height:1.35}</style></head>",
        "<body><main><h1>C300X Agent Setup</h1><section><h2>Auth</h2><div id=\"as\">Not loaded</div><div class=\"g\"><div><label>API token for requests</label><input id=\"ah\" type=\"text\" autocomplete=\"off\" spellcheck=\"false\" placeholder=\"enter token if configured\"></div>"
        "<div><label>Maintenance token for requests</label><input id=\"mh\" type=\"text\" autocomplete=\"off\" spellcheck=\"false\" placeholder=\"enter token if configured\"></div><div><label>New API token</label><input id=\"at\" type=\"text\" autocomplete=\"new-password\" spellcheck=\"false\"></div>"
        "<div><label>New maintenance token</label><input id=\"mt\" type=\"text\" autocomplete=\"off\" spellcheck=\"false\"></div></div><label class=\"opt\"><span><input id=\"na\" type=\"checkbox\"> noAuth</span><small>Allows temporary setup without Bearer auth. Disable it after tokens are saved.</small></label>",
        "<button onclick=\"load()\">Load</button><button onclick=\"save()\">Save</button></section><section><h2>Config</h2><div class=\"g\">"
        "<div><label>API listen host</label><input id=\"lh\"></div><div><label>API port</label><input id=\"ap\" type=\"number\"></div>"
        "<div><label>Internal UI port</label><input id=\"up\" type=\"number\"></div><div><label>UI bind</label><input id=\"ub\" value=\"127.0.0.1 only\" readonly></div>"
        "<div><label>Stair light</label><input id=\"sa\"></div></div>"
        "<label class=\"opt\"><span><input id=\"lan\" type=\"checkbox\"> allow LAN for API</span><small>Lets HA reach the API on the configured host. The internal UI listener stays on localhost.</small></label>"
        "<label class=\"opt\"><span><input id=\"vid\" type=\"checkbox\"> video</span><small>Enables the doorbell SIP/RTSP video bridge. Media starts only when requested.</small></label>"
        "<label class=\"opt\"><span><input id=\"db\" type=\"checkbox\"> display bridge</span><small>Enables the local QML bridge for the HA dashboard and alarm page.</small></label>"
        "<label class=\"opt\"><span><input id=\"ev\" type=\"checkbox\"> events</span><small>Listens for device events and forwards only subscribed event types to HA.</small></label>"
        "<label class=\"opt\"><span><input id=\"mm\" type=\"checkbox\"> memos</span><small>Exposes text and voice memos, including delete support when the GUI patch is active.</small></label>"
        "<label class=\"opt\"><span><input id=\"vm\" type=\"checkbox\"> video messages</span><small>Exposes answering-machine video messages for HA playback and deletion.</small></label>"
        "<label class=\"opt\"><span><input id=\"sm\" type=\"checkbox\"> system metrics</span><small>Publishes CPU, memory, load, and temperature only when HA subscribes to metric events.</small></label>"
        "<label class=\"opt\"><span><input id=\"me\" type=\"checkbox\"> maintenance</span><small>Allows protected maintenance endpoints such as SSH, reboot, GUI reload, QML patch, and firewall.</small></label>"
        "<label class=\"opt\"><span><input id=\"mn\" type=\"checkbox\"> allow noAuth maintenance</span><small>Allows maintenance calls without the maintenance token while noAuth is enabled. Keep this temporary.</small></label>"
        "<label class=\"opt\"><span><input id=\"md\" type=\"checkbox\"> mDNS discovery until HA connects</span><small>Advertises the agent on the local network only while HA is not connected.</small></label>"
        "<label class=\"opt\"><span><input id=\"fw\" type=\"checkbox\"> firewall maintenance</span><small>Allows IPv4 firewall status/apply/restore. Saving this option does not change firewall rules.</small></label>"
        "<label class=\"opt\"><span><input id=\"fw6\" type=\"checkbox\"> IPv6 firewall maintenance</span><small>Allows IPv6 ICMP and API-port rules through ip6tables in the persistent network script.</small></label><button onclick=\"save()\">Save config</button></section>",
        "<section><h2>Manual API</h2><div class=\"g\"><div><label>Endpoint</label><select id=\"ep\" onchange=\"pick()\">",
        "<option value=\"GET /api/v1/health\">GET health</option><option value=\"GET /api/v1/capabilities\">GET capabilities</option>"
        "<option value=\"GET /api/v1/state\">GET state</option><option value=\"GET /api/v1/display-bridge\">GET display bridge</option>"
        "<option value=\"POST /api/v1/display-bridge\">POST display bridge</option><option value=\"GET /api/v1/events/recent\">GET recent events</option>"
        "<option value=\"GET /api/v1/events/subscriptions\">GET event subscriptions</option><option value=\"POST /api/v1/events/subscriptions\">POST event subscription</option>"
        "<option value=\"DELETE /api/v1/events/subscriptions/{id}\">DELETE event subscription</option><option value=\"GET /api/v1/system/metrics\">GET system metrics</option>"
        "<option value=\"GET /api/v1/diagnostics\">GET diagnostics</option><option value=\"GET /api/v1/maintenance/auth\">GET auth config</option>",
        "<option value=\"POST /api/v1/maintenance/auth\">POST auth config</option><option value=\"POST /api/v1/stair-light/actions/activate\">POST stair light</option>"
        "<option value=\"GET /api/v1/smartphone-forwarding\">GET smartphone forwarding</option><option value=\"POST /api/v1/smartphone-forwarding\">POST smartphone forwarding</option>"
        "<option value=\"GET /api/v1/ringer\">GET ringer</option><option value=\"POST /api/v1/ringer\">POST ringer</option>"
        "<option value=\"GET /api/v1/video/doorbell\">GET doorbell video</option><option value=\"GET /api/v1/video/doorbell/status\">GET doorbell video status</option><option value=\"POST /api/v1/video/doorbell/actions/activate\">POST activate doorbell video</option>"
        "<option value=\"POST /api/v1/video/doorbell/actions/stop\">POST stop doorbell video</option><option value=\"GET /api/v1/answering-machine\">GET answering machine</option>"
        "<option value=\"POST /api/v1/answering-machine\">POST answering machine</option><option value=\"GET /api/v1/answering-machine/messages\">GET video messages</option>",
        "<option value=\"GET /api/v1/answering-machine/messages/{id}/video\">GET video message media</option><option value=\"POST /api/v1/answering-machine/messages/actions/delete\">POST delete video message</option>"
        "<option value=\"GET /api/v1/memos\">GET memos</option><option value=\"GET /api/v1/memos/voice/{id}/audio\">GET voice memo audio</option><option value=\"POST /api/v1/memos/actions/delete\">POST delete memo</option>"
        "<option value=\"POST /api/v1/locks/{id}/actions/unlock\">POST unlock lock by id</option><option value=\"POST /api/v1/locks/default/actions/unlock\">POST unlock default lock</option><option value=\"GET /api/v1/maintenance/ssh\">GET SSH status</option>"
        "<option value=\"POST /api/v1/maintenance/ssh\">POST SSH set</option><option value=\"POST /api/v1/maintenance/ssh/actions/start\">POST SSH start</option>"
        "<option value=\"POST /api/v1/maintenance/ssh/actions/stop\">POST SSH stop</option><option value=\"POST /api/v1/maintenance/reboot\">POST reboot</option>"
        "<option value=\"POST /api/v1/maintenance/agent/actions/remove\">POST remove agent</option>"
        "<option value=\"POST /api/v1/maintenance/gui/actions/reload\">POST reload GUI</option><option value=\"GET /api/v1/maintenance/firewall\">GET firewall status</option>"
        "<option value=\"POST /api/v1/maintenance/firewall/actions/apply\">POST apply firewall</option><option value=\"POST /api/v1/maintenance/firewall/actions/restore\">POST restore firewall</option>"
        "<option value=\"GET /api/v1/maintenance/ipv6-firewall\">GET IPv6 firewall status</option><option value=\"POST /api/v1/maintenance/ipv6-firewall/actions/apply\">POST apply IPv6 firewall</option><option value=\"POST /api/v1/maintenance/ipv6-firewall/actions/restore\">POST restore IPv6 firewall</option>"
        "<option value=\"GET /api/v1/maintenance/qml-patch\">GET QML patch status</option>"
        "<option value=\"POST /api/v1/maintenance/qml-patch/actions/apply\">POST apply QML patch</option><option value=\"POST /api/v1/maintenance/qml-patch/actions/restore\">POST restore QML patch</option>",
        "</select></div><div><label>Method</label><select id=\"m\"><option>GET</option><option>POST</option><option>DELETE</option></select></div>"
        "<div><label>Path</label><input id=\"p\" value=\"/api/v1/health\"></div></div><label>JSON body</label><textarea id=\"b\" rows=\"4\"></textarea>"
        "<button onclick=\"call()\">Send</button><button onclick=\"quick('/api/v1/capabilities')\">Capabilities</button><button onclick=\"quick('/api/v1/diagnostics')\">Diagnostics</button></section>",
        "<section><h2>Output</h2><pre id=\"o\"></pre></section><script>const $=i=>document.getElementById(i);"
        "function h(j=1){let x={};if(j)x['Content-Type']='application/json';if($('ah').value)x.Authorization='Bearer '+$('ah').value;if($('mh').value)x['X-Bticino-C300X-Maintenance-Token']=$('mh').value;return x}"
        "function out(q,t){let s=t;try{s=JSON.stringify(JSON.parse(t),null,2)}catch(e){}$('o').textContent=q.status+' '+q.statusText+'\\n'+s}async function r(m,p,b){let q=await fetch(p,{method:m,headers:h(b!==undefined),body:b===undefined?undefined:JSON.stringify(b)}),t=await q.text();out(q,t);try{return JSON.parse(t)}catch(e){return null}}"
        "function yn(v,f){return v?'configured '+(f||''):'missing'}function put(d){if(!d)return;$('as').textContent='noAuth: '+(d.noAuth?'on':'off')+' | API token: '+yn(d.api_token_configured,d.api_token_fingerprint)+' | Maintenance token: '+yn(d.maintenance_token_configured,d.maintenance_token_fingerprint);$('na').checked=!!d.noAuth;$('lh').value=d.listen_host||'';$('ap').value=d.api_port||'';$('up').value=d.ui_port||'';$('ub').value=(d.ui_listen_host||'127.0.0.1')+' only';$('sa').value=d.stair_light_default_address||'';for(let k of [['lan','allow_lan'],['vid','video_enabled'],['db','display_bridge_enabled'],['ev','events_enabled'],['mm','memos_enabled'],['vm','video_messages_enabled'],['sm','system_metrics_enabled'],['me','maintenance_enabled'],['mn','maintenance_no_auth_allowed'],['md','mdns_enabled'],['fw','firewall_enabled'],['fw6','ipv6_firewall_enabled']])$(k[0]).checked=!!d[k[1]]}"
        "async function load(){put(await r('GET','/api/v1/maintenance/auth'))}async function save(){let b={setupComplete:true,noAuth:$('na').checked,listenHost:$('lh').value,apiPort:+$('ap').value,uiPort:+$('up').value,stairLightDefaultAddress:$('sa').value,allowLan:$('lan').checked,videoEnabled:$('vid').checked,displayBridgeEnabled:$('db').checked,eventsEnabled:$('ev').checked,memosEnabled:$('mm').checked,videoMessagesEnabled:$('vm').checked,systemMetricsEnabled:$('sm').checked,maintenanceEnabled:$('me').checked,maintenanceNoAuthAllowed:$('mn').checked,mdnsEnabled:$('md').checked,firewallEnabled:$('fw').checked,ipv6FirewallEnabled:$('fw6').checked};if($('at').value)b.apiToken=$('at').value;if($('mt').value)b.maintenanceToken=$('mt').value;let d=await r('POST','/api/v1/maintenance/auth',b);if(d&&d.ok){if($('at').value)$('ah').value=$('at').value;if($('mt').value)$('mh').value=$('mt').value}$('at').value='';$('mt').value='';put(d)}"
        "function pick(){let v=$('ep').value,i=v.indexOf(' ');$('m').value=v.slice(0,i);$('p').value=v.slice(i+1);$('b').value=''}async function call(){let x=$('b').value.trim(),b=x?JSON.parse(x):undefined;await r($('m').value,$('p').value,b)}function quick(p){$('m').value='GET';$('p').value=p;$('b').value='';call()}pick();load()</script></main></body></html>",
        NULL
    };

    (void)send(client_fd, header, strlen(header), MSG_NOSIGNAL);
    for (size_t index = 0; parts[index] != NULL; index++) {
        (void)send(client_fd, parts[index], strlen(parts[index]), MSG_NOSIGNAL);
    }
}

static void handle_auth_config_get(int client_fd, const struct c300x_config *config)
{
    char listen_host[C300X_JSON_QUOTED_LEN(C300X_MAX_HOST_LEN)];
    char ui_listen_host[C300X_JSON_QUOTED_LEN(sizeof(C300X_UI_LISTEN_HOST))];
    char stair_address[C300X_JSON_QUOTED_LEN(C300X_MAX_ADDRESS_LEN)];
    char api_token_fingerprint[C300X_TOKEN_FINGERPRINT_LEN] = "";
    char maintenance_token_fingerprint[C300X_TOKEN_FINGERPRINT_LEN] = "";
    char api_token_fingerprint_json[C300X_JSON_QUOTED_LEN(C300X_TOKEN_FINGERPRINT_LEN)];
    char maintenance_token_fingerprint_json[C300X_JSON_QUOTED_LEN(C300X_TOKEN_FINGERPRINT_LEN)];
    char body[8192];

    json_string(config->listen_host, listen_host, sizeof(listen_host));
    json_string(C300X_UI_LISTEN_HOST, ui_listen_host, sizeof(ui_listen_host));
    json_string(config->stair_light_default_address, stair_address, sizeof(stair_address));
    if (config->api_token[0] != '\0') {
        fnv1a64_fingerprint(config->api_token, api_token_fingerprint, sizeof(api_token_fingerprint));
    }
    if (config->maintenance_admin_token[0] != '\0') {
        fnv1a64_fingerprint(
            config->maintenance_admin_token,
            maintenance_token_fingerprint,
            sizeof(maintenance_token_fingerprint)
        );
    }
    json_string(api_token_fingerprint, api_token_fingerprint_json, sizeof(api_token_fingerprint_json));
    json_string(
        maintenance_token_fingerprint,
        maintenance_token_fingerprint_json,
        sizeof(maintenance_token_fingerprint_json)
    );
    snprintf(
        body,
        sizeof(body),
        "{"
        "\"ok\":true,"
        "\"noAuth\":%s,"
        "\"no_auth\":%s,"
        "\"restart_required\":%s,"
        "\"api_token_configured\":%s,"
        "\"api_token_fingerprint\":%s,"
        "\"maintenance_token_configured\":%s,"
        "\"maintenance_token_fingerprint\":%s,"
        "\"maintenance_enabled\":%s,"
        "\"maintenance_no_auth_allowed\":%s,"
        "\"mdns_enabled\":%s,"
        "\"firewall_enabled\":%s,"
        "\"ipv6_firewall_enabled\":%s,"
        "\"listen_host\":%s,"
        "\"api_listen_host\":%s,"
        "\"ui_listen_host\":%s,"
        "\"api_port\":%u,"
        "\"ui_port\":%u,"
        "\"allow_lan\":%s,"
        "\"stair_light_default_address\":%s,"
        "\"video_enabled\":%s,"
        "\"display_bridge_enabled\":%s,"
        "\"events_enabled\":%s,"
        "\"memos_enabled\":%s,"
        "\"video_messages_enabled\":%s,"
        "\"system_metrics_enabled\":%s"
        "}\n",
        config->api_no_auth ? "true" : "false",
        config->api_no_auth ? "true" : "false",
        config->restart_required ? "true" : "false",
        config->api_token[0] != '\0' ? "true" : "false",
        api_token_fingerprint_json,
        config->maintenance_admin_token[0] != '\0' ? "true" : "false",
        maintenance_token_fingerprint_json,
        config->maintenance_enabled ? "true" : "false",
        config->maintenance_no_auth_allowed ? "true" : "false",
        config->mdns_enabled ? "true" : "false",
        config->maintenance_firewall_enabled ? "true" : "false",
        config->maintenance_ipv6_firewall_enabled ? "true" : "false",
        listen_host,
        listen_host,
        ui_listen_host,
        config->api_port,
        config->ui_port,
        config->allow_lan ? "true" : "false",
        stair_address,
        config->video_enabled ? "true" : "false",
        config->display_bridge_enabled ? "true" : "false",
        config->events_enabled ? "true" : "false",
        config->memos_enabled ? "true" : "false",
        config->answering_machine_messages_enabled ? "true" : "false",
        config->system_metrics_enabled ? "true" : "false"
    );
    send_json(client_fd, 200, "OK", body);
}

static int json_optional_port(const char *body, const char *field, uint16_t *out)
{
    int value = 0;
    if (!json_int_field(body, field, &value)) {
        return 0;
    }
    if (value < 1 || value > 65535) {
        return -1;
    }
    *out = (uint16_t)value;
    return 1;
}

static void maybe_json_string_field(
    const char *body,
    const char *first_name,
    const char *second_name,
    char *out,
    size_t out_len
)
{
    json_string_field(body, first_name, out, out_len);
    if (out[0] == '\0' && second_name != NULL) {
        json_string_field(body, second_name, out, out_len);
    }
}

static int auth_config_requires_restart(
    const struct c300x_config *current,
    const struct c300x_config *updated
)
{
    return strcmp(current->listen_host, updated->listen_host) != 0
        || current->api_port != updated->api_port
        || current->ui_port != updated->ui_port
        || current->allow_lan != updated->allow_lan
        || current->display_bridge_enabled != updated->display_bridge_enabled
        || current->events_enabled != updated->events_enabled
        || current->video_enabled != updated->video_enabled
        || current->memos_enabled != updated->memos_enabled
        || current->answering_machine_messages_enabled != updated->answering_machine_messages_enabled
        || current->system_metrics_enabled != updated->system_metrics_enabled;
}

static void copy_live_auth_config(
    struct c300x_config *live,
    const struct c300x_config *updated,
    int restart_required
)
{
    live->api_no_auth = updated->api_no_auth;
    snprintf(live->api_token, sizeof(live->api_token), "%s", updated->api_token);
    snprintf(live->api_file_token, sizeof(live->api_file_token), "%s", updated->api_file_token);
    live->api_token_from_env = updated->api_token_from_env;
    snprintf(live->maintenance_admin_token, sizeof(live->maintenance_admin_token), "%s", updated->maintenance_admin_token);
    live->maintenance_enabled = updated->maintenance_enabled;
    live->maintenance_no_auth_allowed = updated->maintenance_no_auth_allowed;
    live->maintenance_firewall_enabled = updated->maintenance_firewall_enabled;
    live->maintenance_ipv6_firewall_enabled = updated->maintenance_ipv6_firewall_enabled;
    live->mdns_enabled = updated->mdns_enabled;
    snprintf(live->stair_light_default_address, sizeof(live->stair_light_default_address), "%s", updated->stair_light_default_address);
    live->restart_required = live->restart_required || restart_required;
}

static void handle_auth_config_post(
    int client_fd,
    struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    struct c300x_config baseline = *config;
    struct c300x_config updated = *config;
    char api_token[C300X_MAX_TOKEN_LEN];
    char maintenance_token[C300X_MAX_TOKEN_LEN];
    char listen_host[C300X_MAX_HOST_LEN];
    char stair_address[C300X_MAX_ADDRESS_LEN];
    char error[C300X_MAX_ERROR_LEN];
    int value = 0;
    int port_result = 0;
    int setup_complete = 0;

    if (!config_admin_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (config->restart_required && config->config_path[0] != '\0') {
        if (c300x_load_config(config->config_path, &baseline, error, sizeof(error))) {
            updated = baseline;
        } else {
            baseline = *config;
        }
    }

    if (json_bool_field(request->body, "noAuth", &value) || json_bool_field(request->body, "no_auth", &value)) {
        updated.api_no_auth = value;
    }
    maybe_json_string_field(request->body, "apiToken", "api_token", api_token, sizeof(api_token));
    if (api_token[0] != '\0') {
        snprintf(updated.api_token, sizeof(updated.api_token), "%s", api_token);
        snprintf(updated.api_file_token, sizeof(updated.api_file_token), "%s", api_token);
        updated.api_token_from_env = 0;
    }
    maybe_json_string_field(
        request->body,
        "maintenanceToken",
        "maintenance_token",
        maintenance_token,
        sizeof(maintenance_token)
    );
    if (maintenance_token[0] != '\0') {
        snprintf(updated.maintenance_admin_token, sizeof(updated.maintenance_admin_token), "%s", maintenance_token);
    }
    maybe_json_string_field(request->body, "listenHost", "listen_host", listen_host, sizeof(listen_host));
    if (listen_host[0] != '\0') {
        snprintf(updated.listen_host, sizeof(updated.listen_host), "%s", listen_host);
    }
    maybe_json_string_field(
        request->body,
        "stairLightDefaultAddress",
        "stair_light_default_address",
        stair_address,
        sizeof(stair_address)
    );
    if (stair_address[0] != '\0') {
        if (!address_is_valid(stair_address)) {
            send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_stair_light_address\"}\n");
            return;
        }
        snprintf(updated.stair_light_default_address, sizeof(updated.stair_light_default_address), "%s", stair_address);
    }
    port_result = json_optional_port(request->body, "apiPort", &updated.api_port);
    if (port_result == 0) {
        port_result = json_optional_port(request->body, "api_port", &updated.api_port);
    }
    if (port_result < 0) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_api_port\"}\n");
        return;
    }
    port_result = json_optional_port(request->body, "uiPort", &updated.ui_port);
    if (port_result == 0) {
        port_result = json_optional_port(request->body, "ui_port", &updated.ui_port);
    }
    if (port_result < 0) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_ui_port\"}\n");
        return;
    }
    if (json_bool_field(request->body, "allowLan", &value) || json_bool_field(request->body, "allow_lan", &value)) {
        updated.allow_lan = value;
    }
    if (json_bool_field(request->body, "videoEnabled", &value) || json_bool_field(request->body, "video_enabled", &value)) {
        updated.video_enabled = value;
    }
    if (json_bool_field(request->body, "displayBridgeEnabled", &value) || json_bool_field(request->body, "display_bridge_enabled", &value)) {
        updated.display_bridge_enabled = value;
    }
    if (json_bool_field(request->body, "eventsEnabled", &value) || json_bool_field(request->body, "events_enabled", &value)) {
        updated.events_enabled = value;
    }
    if (json_bool_field(request->body, "memosEnabled", &value) || json_bool_field(request->body, "memos_enabled", &value)) {
        updated.memos_enabled = value;
    }
    if (json_bool_field(request->body, "videoMessagesEnabled", &value) || json_bool_field(request->body, "video_messages_enabled", &value)) {
        updated.answering_machine_messages_enabled = value;
    }
    if (json_bool_field(request->body, "systemMetricsEnabled", &value) || json_bool_field(request->body, "system_metrics_enabled", &value)) {
        updated.system_metrics_enabled = value;
    }
    if (json_bool_field(request->body, "maintenanceEnabled", &value) || json_bool_field(request->body, "maintenance_enabled", &value)) {
        updated.maintenance_enabled = value;
    }
    if (
        json_bool_field(request->body, "maintenanceNoAuthAllowed", &value)
        || json_bool_field(request->body, "maintenance_no_auth_allowed", &value)
    ) {
        updated.maintenance_no_auth_allowed = value;
    }
    if (json_bool_field(request->body, "mdnsEnabled", &value) || json_bool_field(request->body, "mdns_enabled", &value)) {
        updated.mdns_enabled = value;
    }
    if (json_bool_field(request->body, "firewallEnabled", &value) || json_bool_field(request->body, "firewall_enabled", &value)) {
        updated.maintenance_firewall_enabled = value;
    }
    if (
        json_bool_field(request->body, "ipv6FirewallEnabled", &value)
        || json_bool_field(request->body, "ipv6_firewall_enabled", &value)
    ) {
        updated.maintenance_ipv6_firewall_enabled = value;
    }
    if (json_bool_field(request->body, "setupComplete", &value) || json_bool_field(request->body, "setup_complete", &value)) {
        setup_complete = value;
    }
    if (setup_complete && updated.api_token[0] != '\0') {
        updated.api_no_auth = 0;
        updated.maintenance_no_auth_allowed = 0;
    }

    if (strcmp(updated.listen_host, "127.0.0.1") != 0 && !updated.allow_lan) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"lan_binding_requires_allow_lan\"}\n");
        return;
    }
    if (!updated.api_no_auth && updated.api_token[0] == '\0') {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"api_token_required\"}\n");
        return;
    }
    if (
        updated.maintenance_enabled
        && (
            updated.maintenance_ssh_start_enabled
            || updated.maintenance_reboot_enabled
            || updated.maintenance_gui_reload_enabled
            || updated.maintenance_qml_patch_enabled
            || updated.maintenance_firewall_enabled
        )
        && updated.maintenance_admin_token[0] == '\0'
        && !(updated.api_no_auth && updated.maintenance_no_auth_allowed)
    ) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_token_required\"}\n");
        return;
    }

    if (!c300x_config_persisted_equal(&baseline, &updated)) {
        int restart_required = config->restart_required
            || auth_config_requires_restart(config, &updated);
        int changed = 0;
        if (!c300x_save_config_if_changed(&updated, error, sizeof(error), &changed)) {
            char error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];
            char body[384];
            json_string(error, error_json, sizeof(error_json));
            snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"config_save_failed\",\"detail\":%s}\n", error_json);
            send_json(client_fd, 500, "Internal Server Error", body);
            return;
        }
        if (restart_required) {
            copy_live_auth_config(config, &updated, restart_required);
        } else {
            *config = updated;
        }
        if (changed) {
            record_agent_write(config, runtime, "config", "auth_config");
        }
    }
    handle_auth_config_get(client_fd, config);
}

static int legacy_mqtt_installed(void);
static int legacy_mqtt_startup_enabled(void);
static int legacy_mqtt_running(void);

static void handle_mqtt_status(
    int client_fd,
    const struct c300x_config *config,
    const struct agent_runtime *runtime
)
{
    enum { MQTT_STATUS_BODY_LEN = 8192 };
    struct mqtt_status_workspace {
        char client_id[C300X_JSON_QUOTED_LEN(C300X_MAX_TOKEN_LEN)];
        char command_topic[C300X_JSON_QUOTED_LEN(C300X_MAX_PATH_LEN)];
        char event_topic[C300X_JSON_QUOTED_LEN(C300X_MAX_PATH_LEN)];
        char json_event_topic[C300X_JSON_QUOTED_LEN(C300X_MAX_PATH_LEN)];
        char status_topic[C300X_JSON_QUOTED_LEN(C300X_MAX_PATH_LEN)];
        char availability_topic[C300X_JSON_QUOTED_LEN(C300X_MAX_PATH_LEN)];
        char command_host[C300X_JSON_QUOTED_LEN(C300X_MAX_HOST_LEN)];
        char body[MQTT_STATUS_BODY_LEN];
    };
    struct mqtt_status_workspace *workspace = calloc(1, sizeof(*workspace));
    int written;

    if (workspace == NULL) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        return;
    }
    json_string(config->mqtt_client_id, workspace->client_id, sizeof(workspace->client_id));
    json_string(config->mqtt_command_topic, workspace->command_topic, sizeof(workspace->command_topic));
    json_string(config->mqtt_event_topic, workspace->event_topic, sizeof(workspace->event_topic));
    json_string(config->mqtt_json_event_topic, workspace->json_event_topic, sizeof(workspace->json_event_topic));
    json_string(config->mqtt_status_topic, workspace->status_topic, sizeof(workspace->status_topic));
    json_string(
        config->mqtt_availability_topic,
        workspace->availability_topic,
        sizeof(workspace->availability_topic)
    );
    json_string(config->mqtt_command_host, workspace->command_host, sizeof(workspace->command_host));
    written = snprintf(
        workspace->body,
        sizeof(workspace->body),
        "{"
        "\"ok\":true,"
        "\"enabled\":%s,"
        "\"configured\":%s,"
        "\"connected\":%s,"
        "\"subscribed\":%s,"
        "\"host_configured\":%s,"
        "\"username_configured\":%s,"
        "\"password_configured\":%s,"
        "\"port\":%u,"
        "\"client_id\":%s,"
        "\"command_host\":%s,"
        "\"command_port\":%u,"
        "\"topics\":{\"command\":%s,\"event\":%s,\"json_event\":%s,\"status\":%s,\"availability\":%s},"
        "\"qos\":%d,"
        "\"keepalive_seconds\":%d,"
        "\"reconnect_initial_seconds\":%d,"
        "\"reconnect_max_seconds\":%d,"
        "\"legacy_installed\":%s,"
        "\"legacy_enabled\":%s,"
        "\"legacy_running\":%s,"
        "\"exclusive\":true"
        "}\n",
        config->mqtt_enabled ? "true" : "false",
        (config->mqtt_host[0] != '\0') ? "true" : "false",
        (runtime != NULL && runtime->mqtt.connected) ? "true" : "false",
        (runtime != NULL && runtime->mqtt.subscribed) ? "true" : "false",
        config->mqtt_host[0] != '\0' ? "true" : "false",
        config->mqtt_username[0] != '\0' ? "true" : "false",
        config->mqtt_password[0] != '\0' ? "true" : "false",
        config->mqtt_port,
        workspace->client_id,
        workspace->command_host,
        config->mqtt_command_port,
        workspace->command_topic,
        workspace->event_topic,
        workspace->json_event_topic,
        workspace->status_topic,
        workspace->availability_topic,
        config->mqtt_qos,
        config->mqtt_keepalive_seconds,
        config->mqtt_reconnect_initial_seconds,
        config->mqtt_reconnect_max_seconds,
        legacy_mqtt_installed() ? "true" : "false",
        legacy_mqtt_startup_enabled() ? "true" : "false",
        legacy_mqtt_running() ? "true" : "false"
    );
    if (written < 0 || written >= (int)sizeof(workspace->body)) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"mqtt_status_too_large\"}\n");
        free(workspace);
        return;
    }
    send_json(client_fd, 200, "OK", workspace->body);
    free(workspace);
}

static int mqtt_runtime_config_is_valid(const struct c300x_config *config, const char **error)
{
    if (config->mqtt_enabled && config->mqtt_host[0] == '\0') {
        *error = "mqtt_host_required";
        return 0;
    }
    if (config->mqtt_enabled && config->mqtt_client_id[0] == '\0') {
        *error = "mqtt_client_id_required";
        return 0;
    }
    if (config->mqtt_enabled && config->mqtt_command_topic[0] != '\0' && config->mqtt_command_host[0] == '\0') {
        *error = "mqtt_command_host_required";
        return 0;
    }
    if (config->mqtt_qos != 0) {
        *error = "mqtt_qos_unsupported";
        return 0;
    }
    if (config->mqtt_keepalive_seconds < 10) {
        *error = "mqtt_keepalive_too_low";
        return 0;
    }
    if (config->mqtt_reconnect_initial_seconds < 1) {
        *error = "mqtt_reconnect_initial_too_low";
        return 0;
    }
    if (config->mqtt_reconnect_max_seconds < config->mqtt_reconnect_initial_seconds) {
        *error = "mqtt_reconnect_max_too_low";
        return 0;
    }
    return 1;
}

static void firewall_remount_rw_if_needed(const char *path);
static void firewall_remount_ro_if_needed(const char *path);
static int run_detached_command(const char *program, const char *argument, int delay_ms);

static int process_cmdline_contains(const char *needle)
{
    DIR *directory;
    struct dirent *entry;

    directory = opendir("/proc");
    if (directory == NULL) {
        return 0;
    }
    while ((entry = readdir(directory)) != NULL) {
        char path[512];
        char buffer[512];
        FILE *file;
        size_t read_len;
        int is_pid = 1;

        for (const char *ptr = entry->d_name; *ptr != '\0'; ptr++) {
            if (!isdigit((unsigned char)*ptr)) {
                is_pid = 0;
                break;
            }
        }
        if (!is_pid) {
            continue;
        }
        if (snprintf(path, sizeof(path), "/proc/%s/cmdline", entry->d_name) >= (int)sizeof(path)) {
            continue;
        }
        file = fopen(path, "r");
        if (file == NULL) {
            continue;
        }
        read_len = fread(buffer, 1, sizeof(buffer) - 1, file);
        fclose(file);
        if (read_len == 0) {
            continue;
        }
        buffer[read_len] = '\0';
        for (size_t index = 0; index < read_len; index++) {
            if (buffer[index] == '\0') {
                buffer[index] = ' ';
            }
        }
        if (strstr(buffer, needle) != NULL) {
            closedir(directory);
            return 1;
        }
    }
    closedir(directory);
    return 0;
}

static int legacy_mqtt_installed(void)
{
    return path_exists(C300X_LEGACY_MQTT_SCRIPT)
        || path_exists(C300X_LEGACY_MQTT_DIR)
        || path_exists(C300X_LEGACY_MQTT_INIT_LINK)
        || path_exists("/home/root/filter.py")
        || path_exists("/etc/init.d/flexisipsh_bak");
}

static int legacy_mqtt_startup_enabled(void)
{
    return path_exists(C300X_LEGACY_MQTT_INIT_LINK);
}

static int legacy_mqtt_backup_available(void)
{
    return path_exists(C300X_LEGACY_MQTT_BACKUP_MARKER);
}

static int legacy_mqtt_running(void)
{
    return process_cmdline_contains("TcpDump2Mqtt")
        || process_cmdline_contains("StartMqttSend")
        || process_cmdline_contains("StartMqttReceive")
        || process_cmdline_contains("mosquitto_sub")
        || process_cmdline_contains("mosquitto_pub");
}

static void legacy_mqtt_stop_processes(void)
{
    int status;

    status = system("pkill -f StartMqttSend >/dev/null 2>&1");
    (void)status;
    status = system("pkill -f StartMqttReceive >/dev/null 2>&1");
    (void)status;
    status = system("pkill -f TcpDump2Mqtt >/dev/null 2>&1");
    (void)status;
    status = system("pkill -f 'mosquitto_sub.*Bticino/rx' >/dev/null 2>&1");
    (void)status;
    status = system("pkill -f 'mosquitto_pub.*Bticino/tx' >/dev/null 2>&1");
    (void)status;
}

static int run_fixed_shell_command(const char *command)
{
    int status = system(command);
    if (status == -1) {
        return 0;
    }
    return WIFEXITED(status) && WEXITSTATUS(status) == 0;
}

static int copy_trimmed_config_value(char *target, size_t target_len, const char *value)
{
    char buffer[512];
    char *trimmed;
    size_t len;

    if (target_len == 0 || value == NULL) {
        return 0;
    }
    if (snprintf(buffer, sizeof(buffer), "%s", value) >= (int)sizeof(buffer)) {
        return 0;
    }
    trimmed = (char *)trim_ascii(buffer);
    len = strlen(trimmed);
    if (
        len >= 2
        && ((trimmed[0] == '"' && trimmed[len - 1] == '"') || (trimmed[0] == '\'' && trimmed[len - 1] == '\''))
    ) {
        trimmed[len - 1] = '\0';
        trimmed++;
        trimmed = (char *)trim_ascii(trimmed);
    }
    if (strlen(trimmed) >= target_len) {
        return 0;
    }
    snprintf(target, target_len, "%s", trimmed);
    return 1;
}

static int legacy_mqtt_copy_nonempty_value(char *target, size_t target_len, const char *value, int *imported)
{
    char buffer[512];

    if (!copy_trimmed_config_value(buffer, sizeof(buffer), value)) {
        return 0;
    }
    if (buffer[0] == '\0') {
        return 1;
    }
    if (strlen(buffer) >= target_len) {
        return 0;
    }
    snprintf(target, target_len, "%s", buffer);
    if (imported != NULL) {
        *imported = 1;
    }
    return 1;
}

static int legacy_mqtt_copy_optional_value(char *target, size_t target_len, const char *value, int *imported)
{
    if (!copy_trimmed_config_value(target, target_len, value)) {
        return 0;
    }
    if (imported != NULL) {
        *imported = 1;
    }
    return 1;
}

static int legacy_mqtt_import_port(const char *value, uint16_t *port, int *imported)
{
    char buffer[32];
    char *end = NULL;
    long parsed;

    if (!copy_trimmed_config_value(buffer, sizeof(buffer), value)) {
        return 0;
    }
    if (buffer[0] == '\0') {
        return 1;
    }
    errno = 0;
    parsed = strtol(buffer, &end, 10);
    if (errno != 0 || end == NULL || *end != '\0' || parsed <= 0 || parsed > 65535) {
        return 0;
    }
    *port = (uint16_t)parsed;
    if (imported != NULL) {
        *imported = 1;
    }
    return 1;
}

static int legacy_mqtt_import_config(struct c300x_config *updated, int *imported)
{
    char content[8192];
    char *line;
    char *saveptr = NULL;
    int truncated = 0;

    if (imported != NULL) {
        *imported = 0;
    }
    if (!path_exists(C300X_LEGACY_MQTT_CONFIG)) {
        return 1;
    }
    if (!read_bounded_text_file(C300X_LEGACY_MQTT_CONFIG, content, sizeof(content), &truncated) || truncated) {
        return 0;
    }
    line = strtok_r(content, "\n", &saveptr);
    while (line != NULL) {
        char *trimmed = (char *)trim_ascii(line);
        char *equals;
        char *key;
        char *value;

        if (trimmed[0] == '\0' || trimmed[0] == '#') {
            line = strtok_r(NULL, "\n", &saveptr);
            continue;
        }
        equals = strchr(trimmed, '=');
        if (equals == NULL) {
            line = strtok_r(NULL, "\n", &saveptr);
            continue;
        }
        *equals = '\0';
        key = (char *)trim_ascii(trimmed);
        value = (char *)trim_ascii(equals + 1);

        if (strcmp(key, "MQTT_HOST") == 0) {
            if (!legacy_mqtt_copy_nonempty_value(updated->mqtt_host, sizeof(updated->mqtt_host), value, imported)) {
                return 0;
            }
        } else if (strcmp(key, "MQTT_PORT") == 0) {
            if (!legacy_mqtt_import_port(value, &updated->mqtt_port, imported)) {
                return 0;
            }
        } else if (strcmp(key, "MQTT_USER") == 0) {
            if (!legacy_mqtt_copy_optional_value(updated->mqtt_username, sizeof(updated->mqtt_username), value, imported)) {
                return 0;
            }
        } else if (strcmp(key, "MQTT_PASS") == 0) {
            if (!legacy_mqtt_copy_optional_value(updated->mqtt_password, sizeof(updated->mqtt_password), value, imported)) {
                return 0;
            }
        } else if (strcmp(key, "TOPIC_RX") == 0) {
            if (!legacy_mqtt_copy_nonempty_value(updated->mqtt_command_topic, sizeof(updated->mqtt_command_topic), value, imported)) {
                return 0;
            }
        } else if (strcmp(key, "TOPIC_DUMP") == 0) {
            if (!legacy_mqtt_copy_nonempty_value(updated->mqtt_event_topic, sizeof(updated->mqtt_event_topic), value, imported)) {
                return 0;
            }
        } else if (strcmp(key, "TOPIC_STARTD") == 0) {
            if (!legacy_mqtt_copy_nonempty_value(updated->mqtt_status_topic, sizeof(updated->mqtt_status_topic), value, imported)) {
                return 0;
            }
        } else if (strcmp(key, "TOPIC_LASTWILL") == 0) {
            if (!legacy_mqtt_copy_nonempty_value(updated->mqtt_availability_topic, sizeof(updated->mqtt_availability_topic), value, imported)) {
                return 0;
            }
        }
        line = strtok_r(NULL, "\n", &saveptr);
    }
    return 1;
}

static int legacy_mqtt_backup_if_needed(int *changed)
{
    if (changed != NULL) {
        *changed = 0;
    }
    if (legacy_mqtt_backup_available()) {
        return 1;
    }
    if (!legacy_mqtt_installed() && !path_exists("/etc/init.d/flexisipsh_bak")) {
        return 1;
    }
    if (!run_fixed_shell_command(
        "mkdir -p " C300X_LEGACY_MQTT_BACKUP_DIR "/etc "
        C300X_LEGACY_MQTT_BACKUP_DIR "/home/root "
        C300X_LEGACY_MQTT_BACKUP_DIR "/etc/init.d"
    )) {
        return 0;
    }
    if (path_exists(C300X_LEGACY_MQTT_DIR)
        && !run_fixed_shell_command(
            "rm -rf " C300X_LEGACY_MQTT_BACKUP_DIR "/etc/tcpdump2mqtt "
            "&& cp -a /etc/tcpdump2mqtt " C300X_LEGACY_MQTT_BACKUP_DIR "/etc/"
        )) {
        return 0;
    }
    if (path_exists("/home/root/filter.py")
        && !copy_binary_file(
            "/home/root/filter.py",
            C300X_LEGACY_MQTT_BACKUP_DIR "/home/root/filter.py",
            0700
        )) {
        return 0;
    }
    if (path_exists("/etc/init.d/flexisipsh")
        && !copy_binary_file(
            "/etc/init.d/flexisipsh",
            C300X_LEGACY_MQTT_BACKUP_DIR "/etc/init.d/flexisipsh",
            0700
        )) {
        return 0;
    }
    if (path_exists("/etc/init.d/flexisipsh_bak")
        && !copy_binary_file(
            "/etc/init.d/flexisipsh_bak",
            C300X_LEGACY_MQTT_BACKUP_DIR "/etc/init.d/flexisipsh_bak",
            0700
        )) {
        return 0;
    }
    if (!copy_binary_file("/dev/null", C300X_LEGACY_MQTT_BACKUP_MARKER, 0600)) {
        return 0;
    }
    if (changed != NULL) {
        *changed = 1;
    }
    return 1;
}

static int legacy_mqtt_restore_from_backup(int *changed)
{
    char current[256];
    ssize_t len;

    if (changed != NULL) {
        *changed = 0;
    }
    if (!legacy_mqtt_backup_available()) {
        return 0;
    }
    if (path_exists(C300X_LEGACY_MQTT_BACKUP_DIR "/etc/tcpdump2mqtt")
        && !run_fixed_shell_command(
            "rm -rf /etc/tcpdump2mqtt "
            "&& cp -a " C300X_LEGACY_MQTT_BACKUP_DIR "/etc/tcpdump2mqtt /etc/"
        )) {
        return 0;
    }
    if (path_exists(C300X_LEGACY_MQTT_BACKUP_DIR "/home/root/filter.py")
        && !copy_binary_file(
            C300X_LEGACY_MQTT_BACKUP_DIR "/home/root/filter.py",
            "/home/root/filter.py",
            0700
        )) {
        return 0;
    }
    if (path_exists(C300X_LEGACY_MQTT_BACKUP_DIR "/etc/init.d/flexisipsh")
        && !copy_binary_file(
            C300X_LEGACY_MQTT_BACKUP_DIR "/etc/init.d/flexisipsh",
            "/etc/init.d/flexisipsh",
            0700
        )) {
        return 0;
    }
    if (path_exists(C300X_LEGACY_MQTT_BACKUP_DIR "/etc/init.d/flexisipsh_bak")
        && !copy_binary_file(
            C300X_LEGACY_MQTT_BACKUP_DIR "/etc/init.d/flexisipsh_bak",
            "/etc/init.d/flexisipsh_bak",
            0700
        )) {
        return 0;
    }
    len = readlink(C300X_LEGACY_MQTT_INIT_LINK, current, sizeof(current) - 1);
    if (len >= 0) {
        current[len] = '\0';
        if (strcmp(current, C300X_LEGACY_MQTT_INIT_TARGET) == 0) {
            if (changed != NULL) {
                *changed = 1;
            }
            return 1;
        }
        if (unlink(C300X_LEGACY_MQTT_INIT_LINK) != 0) {
            return 0;
        }
    } else if (errno != ENOENT) {
        return 0;
    }
    if (symlink(C300X_LEGACY_MQTT_INIT_TARGET, C300X_LEGACY_MQTT_INIT_LINK) != 0) {
        return 0;
    }
    if (changed != NULL) {
        *changed = 1;
    }
    return 1;
}

static int legacy_mqtt_remove_patch(int *changed)
{
    int had_legacy_patch = legacy_mqtt_installed();
    int had_tcpdump2mqtt = path_exists(C300X_LEGACY_MQTT_DIR);

    if (changed != NULL) {
        *changed = 0;
    }
    if (!legacy_mqtt_backup_if_needed(changed)) {
        return 0;
    }
    if (!had_legacy_patch) {
        return 1;
    }
    if (unlink(C300X_LEGACY_MQTT_INIT_LINK) != 0 && errno != ENOENT) {
        return 0;
    }
    if (path_exists("/etc/init.d/flexisipsh_bak")
        && !copy_binary_file("/etc/init.d/flexisipsh_bak", "/etc/init.d/flexisipsh", 0700)) {
        return 0;
    } else if (!path_exists("/etc/init.d/flexisipsh_bak")
        && path_exists("/etc/init.d/flexisipsh")
        && !run_fixed_shell_command(
            "sed '/\\/tmp\\/flexisip_restarted/d' /etc/init.d/flexisipsh >/tmp/c300x-flexisipsh "
            "&& cp /tmp/c300x-flexisipsh /etc/init.d/flexisipsh "
            "&& chmod 700 /etc/init.d/flexisipsh "
            "&& rm -f /tmp/c300x-flexisipsh"
        )) {
        return 0;
    }
    (void)unlink("/etc/init.d/flexisipsh_bak");
    if (!remove_tree(C300X_LEGACY_MQTT_DIR)) {
        return 0;
    }
    if ((had_tcpdump2mqtt || path_exists(C300X_LEGACY_MQTT_BACKUP_DIR "/home/root/filter.py"))
        && unlink("/home/root/filter.py") != 0 && errno != ENOENT) {
        return 0;
    }
    if (changed != NULL && had_legacy_patch) {
        *changed = 1;
    }
    return 1;
}

static void handle_legacy_mqtt_status(
    int client_fd,
    const struct c300x_config *config
)
{
    char body[512];

    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"available\":true,\"installed\":%s,\"enabled\":%s,\"running\":%s,\"backup_available\":%s,\"native_enabled\":%s,\"exclusive\":true,\"script_path\":\"%s\",\"init_link\":\"%s\"}\n",
        legacy_mqtt_installed() ? "true" : "false",
        legacy_mqtt_startup_enabled() ? "true" : "false",
        legacy_mqtt_running() ? "true" : "false",
        legacy_mqtt_backup_available() ? "true" : "false",
        (config != NULL && config->mqtt_enabled) ? "true" : "false",
        C300X_LEGACY_MQTT_SCRIPT,
        C300X_LEGACY_MQTT_INIT_LINK
    );
    send_json(client_fd, 200, "OK", body);
}

static void handle_legacy_mqtt_post(
    int client_fd,
    struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    int enabled = 0;
    int changed = 0;
    int native_config_changed = 0;
    int should_start_legacy = 0;
    int should_stop_legacy = 0;
    char error[C300X_MAX_ERROR_LEN];

    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!json_bool_field(request->body, "enabled", &enabled)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"enabled_required\"}\n");
        return;
    }
    if (enabled && !legacy_mqtt_backup_available()) {
        send_json(client_fd, 409, "Conflict", "{\"ok\":false,\"error\":\"legacy_mqtt_backup_missing\"}\n");
        return;
    }
    if (enabled && config->mqtt_enabled) {
        struct c300x_config updated = *config;
        updated.mqtt_enabled = 0;
        if (!c300x_save_config_if_changed(&updated, error, sizeof(error), &native_config_changed)) {
            char error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];
            char body[256];
            json_string(error, error_json, sizeof(error_json));
            snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"config_save_failed\",\"detail\":%s}\n", error_json);
            send_json(client_fd, 500, "Internal Server Error", body);
            return;
        }
        *config = updated;
        if (runtime != NULL) {
            c300x_mqtt_close(&runtime->mqtt);
        }
        if (native_config_changed) {
            record_agent_write(config, runtime, "config", "mqtt_disabled_for_legacy");
        }
    }
    firewall_remount_rw_if_needed(C300X_LEGACY_MQTT_INIT_LINK);
    if (enabled) {
        if (!legacy_mqtt_restore_from_backup(&changed)) {
            firewall_remount_ro_if_needed(C300X_LEGACY_MQTT_INIT_LINK);
            send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"legacy_mqtt_restore_failed\"}\n");
            return;
        }
        should_start_legacy = 1;
    } else {
        if (!legacy_mqtt_remove_patch(&changed)) {
            firewall_remount_ro_if_needed(C300X_LEGACY_MQTT_INIT_LINK);
            send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"legacy_mqtt_remove_failed\"}\n");
            return;
        }
        should_stop_legacy = 1;
    }
    firewall_remount_ro_if_needed(C300X_LEGACY_MQTT_INIT_LINK);
    if (should_stop_legacy) {
        legacy_mqtt_stop_processes();
    }
    if (should_start_legacy) {
        (void)run_detached_command(C300X_LEGACY_MQTT_SCRIPT, NULL, 0);
    }
    if (changed) {
        record_agent_write(config, runtime, "legacy_mqtt", enabled ? "restore" : "remove");
    }
    handle_legacy_mqtt_status(client_fd, config);
}

static void handle_mqtt_migrate_legacy_post(
    int client_fd,
    struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    struct c300x_config *updated;
    char error[C300X_MAX_ERROR_LEN];
    const char *validation_error = NULL;
    char validation_error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];
    char body[1024];
    int legacy_was_installed;
    int legacy_was_enabled;
    int legacy_was_running;
    int legacy_was_active;
    int imported_config = 0;
    int legacy_changed = 0;
    int config_changed = 0;

    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!confirm_matches(request, "migrate_legacy_mqtt")) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return;
    }
    updated = malloc(sizeof(*updated));
    if (updated == NULL) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        return;
    }
    *updated = *config;

    legacy_was_installed = legacy_mqtt_installed();
    legacy_was_enabled = legacy_mqtt_startup_enabled();
    legacy_was_running = legacy_mqtt_running();
    legacy_was_active = legacy_was_enabled || legacy_was_running;

    if (legacy_was_active) {
        if (!legacy_mqtt_import_config(updated, &imported_config)) {
            send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"legacy_mqtt_import_failed\"}\n");
            free(updated);
            return;
        }
        if (updated->mqtt_host[0] != '\0') {
            updated->mqtt_enabled = 1;
        }
    }

    if (!mqtt_runtime_config_is_valid(updated, &validation_error)) {
        json_string(validation_error, validation_error_json, sizeof(validation_error_json));
        snprintf(body, sizeof(body), "{\"ok\":false,\"error\":%s}\n", validation_error_json);
        send_json(client_fd, 400, "Bad Request", body);
        free(updated);
        return;
    }

    if (!c300x_config_persisted_equal(config, updated)) {
        if (!c300x_save_config_if_changed(updated, error, sizeof(error), &config_changed)) {
            char error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];
            json_string(error, error_json, sizeof(error_json));
            snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"config_save_failed\",\"detail\":%s}\n", error_json);
            send_json(client_fd, 500, "Internal Server Error", body);
            free(updated);
            return;
        }
        *config = *updated;
        if (runtime != NULL) {
            c300x_mqtt_close(&runtime->mqtt);
            c300x_mqtt_reset_retry(&runtime->mqtt);
        }
    }

    if (legacy_was_installed && legacy_was_active) {
        firewall_remount_rw_if_needed(C300X_LEGACY_MQTT_INIT_LINK);
        if (!legacy_mqtt_remove_patch(&legacy_changed)) {
            firewall_remount_ro_if_needed(C300X_LEGACY_MQTT_INIT_LINK);
            send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"legacy_mqtt_remove_failed\"}\n");
            free(updated);
            return;
        }
        firewall_remount_ro_if_needed(C300X_LEGACY_MQTT_INIT_LINK);
        legacy_mqtt_stop_processes();
    }

    if (legacy_changed) {
        record_agent_write(config, runtime, "legacy_mqtt", "migrate_remove");
    }
    if (config_changed) {
        record_agent_write(config, runtime, "config", "mqtt_migrated_from_legacy");
    }

    snprintf(
        body,
        sizeof(body),
        "{"
        "\"ok\":true,"
        "\"available\":true,"
        "\"migrated\":%s,"
        "\"legacy_was_installed\":%s,"
        "\"legacy_was_enabled\":%s,"
        "\"legacy_was_running\":%s,"
        "\"legacy_removed\":%s,"
        "\"legacy_backup_available\":%s,"
        "\"imported_config\":%s,"
        "\"native_enabled\":%s,"
        "\"native_configured\":%s"
        "}\n",
        (legacy_changed || config_changed) ? "true" : "false",
        legacy_was_installed ? "true" : "false",
        legacy_was_enabled ? "true" : "false",
        legacy_was_running ? "true" : "false",
        !legacy_mqtt_installed() ? "true" : "false",
        legacy_mqtt_backup_available() ? "true" : "false",
        imported_config ? "true" : "false",
        config->mqtt_enabled ? "true" : "false",
        config->mqtt_host[0] != '\0' ? "true" : "false"
    );
    send_json(client_fd, 200, "OK", body);
    free(updated);
}

static int maybe_json_mqtt_string(
    const char *body,
    const char *field,
    char *out,
    size_t out_len
)
{
    char pattern[64];
    const char *found;
    const char *ptr;
    size_t written = 0;

    if (out_len == 0) {
        return -1;
    }
    snprintf(pattern, sizeof(pattern), "\"%s\"", field);
    found = strstr(body, pattern);
    if (found == NULL) {
        return 0;
    }
    ptr = strchr(found + strlen(pattern), ':');
    if (ptr == NULL) {
        return -1;
    }
    ptr++;
    while (*ptr != '\0' && isspace((unsigned char)*ptr)) {
        ptr++;
    }
    if (*ptr != '"') {
        return -1;
    }
    ptr++;
    while (*ptr != '\0' && *ptr != '"') {
        char ch = *ptr++;
        if (ch == '\\' && *ptr != '\0') {
            ch = *ptr++;
        }
        if (written + 1 >= out_len) {
            return -1;
        }
        out[written++] = ch;
    }
    if (*ptr != '"') {
        return -1;
    }
    out[written] = '\0';
    return 1;
}

static void handle_mqtt_post(
    int client_fd,
    struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    struct c300x_config updated = *config;
    char error[C300X_MAX_ERROR_LEN];
    const char *validation_error = NULL;
    char validation_error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];
    char body[2048];
    int value = 0;
    int port_result;
    int legacy_changed = 0;

    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (json_bool_field(request->body, "enabled", &value) || json_bool_field(request->body, "mqttEnabled", &value) || json_bool_field(request->body, "mqtt_enabled", &value)) {
        updated.mqtt_enabled = value;
    }
    if (
        maybe_json_mqtt_string(request->body, "host", updated.mqtt_host, sizeof(updated.mqtt_host)) < 0
        || maybe_json_mqtt_string(request->body, "username", updated.mqtt_username, sizeof(updated.mqtt_username)) < 0
        || maybe_json_mqtt_string(request->body, "password", updated.mqtt_password, sizeof(updated.mqtt_password)) < 0
        || maybe_json_mqtt_string(request->body, "clientId", updated.mqtt_client_id, sizeof(updated.mqtt_client_id)) < 0
        || maybe_json_mqtt_string(request->body, "client_id", updated.mqtt_client_id, sizeof(updated.mqtt_client_id)) < 0
        || maybe_json_mqtt_string(request->body, "commandHost", updated.mqtt_command_host, sizeof(updated.mqtt_command_host)) < 0
        || maybe_json_mqtt_string(request->body, "command_host", updated.mqtt_command_host, sizeof(updated.mqtt_command_host)) < 0
        || maybe_json_mqtt_string(request->body, "commandTopic", updated.mqtt_command_topic, sizeof(updated.mqtt_command_topic)) < 0
        || maybe_json_mqtt_string(request->body, "eventTopic", updated.mqtt_event_topic, sizeof(updated.mqtt_event_topic)) < 0
        || maybe_json_mqtt_string(request->body, "jsonEventTopic", updated.mqtt_json_event_topic, sizeof(updated.mqtt_json_event_topic)) < 0
        || maybe_json_mqtt_string(request->body, "statusTopic", updated.mqtt_status_topic, sizeof(updated.mqtt_status_topic)) < 0
        || maybe_json_mqtt_string(request->body, "availabilityTopic", updated.mqtt_availability_topic, sizeof(updated.mqtt_availability_topic)) < 0
    ) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_mqtt_string\"}\n");
        return;
    }
    port_result = json_optional_port(request->body, "port", &updated.mqtt_port);
    if (port_result < 0) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_mqtt_port\"}\n");
        return;
    }
    port_result = json_optional_port(request->body, "commandPort", &updated.mqtt_command_port);
    if (port_result == 0) {
        port_result = json_optional_port(request->body, "command_port", &updated.mqtt_command_port);
    }
    if (port_result < 0) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_mqtt_command_port\"}\n");
        return;
    }
    if (json_int_field(request->body, "keepaliveSeconds", &value) || json_int_field(request->body, "keepalive_seconds", &value)) {
        updated.mqtt_keepalive_seconds = value;
    }
    if (json_int_field(request->body, "reconnectInitialSeconds", &value) || json_int_field(request->body, "reconnect_initial_seconds", &value)) {
        updated.mqtt_reconnect_initial_seconds = value;
    }
    if (json_int_field(request->body, "reconnectMaxSeconds", &value) || json_int_field(request->body, "reconnect_max_seconds", &value)) {
        updated.mqtt_reconnect_max_seconds = value;
    }
    if (!mqtt_runtime_config_is_valid(&updated, &validation_error)) {
        json_string(validation_error, validation_error_json, sizeof(validation_error_json));
        snprintf(body, sizeof(body), "{\"ok\":false,\"error\":%s}\n", validation_error_json);
        send_json(client_fd, 400, "Bad Request", body);
        return;
    }
    if (!c300x_config_persisted_equal(config, &updated)) {
        int changed = 0;
        if (!c300x_save_config_if_changed(&updated, error, sizeof(error), &changed)) {
            char error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];
            json_string(error, error_json, sizeof(error_json));
            snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"config_save_failed\",\"detail\":%s}\n", error_json);
            send_json(client_fd, 500, "Internal Server Error", body);
            return;
        }
        *config = updated;
        c300x_mqtt_close(&runtime->mqtt);
        c300x_mqtt_reset_retry(&runtime->mqtt);
        if (changed) {
            record_agent_write(config, runtime, "config", "mqtt");
        }
    }
    if (updated.mqtt_enabled && legacy_mqtt_installed()) {
        firewall_remount_rw_if_needed(C300X_LEGACY_MQTT_INIT_LINK);
        if (!legacy_mqtt_remove_patch(&legacy_changed)) {
            firewall_remount_ro_if_needed(C300X_LEGACY_MQTT_INIT_LINK);
            send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"legacy_mqtt_remove_failed\"}\n");
            return;
        }
        firewall_remount_ro_if_needed(C300X_LEGACY_MQTT_INIT_LINK);
        legacy_mqtt_stop_processes();
        if (legacy_changed) {
            record_agent_write(config, runtime, "legacy_mqtt", "remove_for_native");
        }
    }
    handle_mqtt_status(client_fd, config, runtime);
}

static void handle_subscription_delete(
    int client_fd,
    struct agent_runtime *runtime,
    const struct c300x_config *config,
    const char *id
)
{
    for (int index = 0; index < runtime->subscription_count; index++) {
        if (strcmp(runtime->subscriptions[index].id, id) != 0) {
            continue;
        }
        for (int move = index + 1; move < runtime->subscription_count; move++) {
            runtime->subscriptions[move - 1] = runtime->subscriptions[move];
        }
        runtime->subscription_count--;
        save_subscriptions(config, runtime, config->subscription_store_path, "deleted");
        send_json(client_fd, 200, "OK", "{\"ok\":true}\n");
        return;
    }
    send_json(client_fd, 404, "Not Found", "{\"ok\":false}\n");
}

static void dispatch_event(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const char *event_type,
    const char *data_json,
    int ttl_seconds
)
{
    char occurred_at[40];
    char event_json[2048];
    char event_type_json[C300X_JSON_QUOTED_LEN(64)];
    int written;

    utc_now(occurred_at, sizeof(occurred_at));
    json_string(event_type, event_type_json, sizeof(event_type_json));
    written = snprintf(
        event_json,
        sizeof(event_json),
        "{\"event_id\":\"native-%ld-%d\",\"type\":%s,\"occurred_at\":\"%s\",\"ttl_seconds\":%d,\"data\":%s}",
        (long)time(NULL),
        runtime->recent_count,
        event_type_json,
        occurred_at,
        ttl_seconds,
        data_json
    );
    if (written < 0 || (size_t)written >= sizeof(event_json)) {
        return;
    }
    c300x_mqtt_publish_event(&runtime->mqtt, config, event_type, event_json, data_json);
    if (!has_matching_subscription(runtime, event_type)) {
        return;
    }
    record_recent_event(runtime, event_json);
    if (!runtime_network_online(runtime, time(NULL))) {
        for (int index = 0; index < runtime->subscription_count; index++) {
            struct subscription *subscription = &runtime->subscriptions[index];
            if (!subscription_matches_event(subscription, event_type)) {
                continue;
            }
            subscription->last_ok = 0;
            snprintf(subscription->last_event_type, sizeof(subscription->last_event_type), "%s", event_type);
        }
        return;
    }
    for (int index = 0; index < runtime->subscription_count; index++) {
        struct subscription *subscription = &runtime->subscriptions[index];
        if (!subscription_matches_event(subscription, event_type)) {
            continue;
        }
        subscription->last_ok = post_callback(config, subscription, event_json);
        if (subscription->last_ok) {
            mark_home_assistant_callback_seen(runtime, time(NULL));
        }
        snprintf(subscription->last_event_type, sizeof(subscription->last_event_type), "%s", event_type);
        utc_now(subscription->last_delivered_at, sizeof(subscription->last_delivered_at));
    }
    if (strcmp(event_type, "system.metrics_changed") != 0) {
        if (event_requests_metrics_refresh(event_type)) {
            system_metrics_dispatch_now(config, runtime, time(NULL));
        }
    }
}

static int has_matching_subscription(
    const struct agent_runtime *runtime,
    const char *event_type
)
{
    if (runtime == NULL) {
        return 0;
    }
    for (int index = 0; index < runtime->subscription_count; index++) {
        if (subscription_matches_event(&runtime->subscriptions[index], event_type)) {
            return 1;
        }
    }
    return 0;
}

static int system_metrics_watch_active(
    const struct c300x_config *config,
    const struct agent_runtime *runtime
)
{
    return config->system_metrics_enabled
        && config->system_metrics_watch
        && has_matching_subscription(runtime, "system.metrics_changed");
}

static int timeout_until_ms(time_t now, time_t due)
{
    if (due <= now) {
        return 0;
    }
    if (due - now > 3600) {
        return 3600000;
    }
    return (int)((due - now) * 1000);
}

static int min_timeout_ms(int current, int candidate)
{
    if (candidate < 0) {
        return current;
    }
    if (current < 0 || candidate < current) {
        return candidate;
    }
    return current;
}

static int system_metrics_changed(
    const struct c300x_config *config,
    const struct system_metrics_sample *previous,
    const struct system_metrics_sample *current
)
{
    if (
        previous->has_cpu_usage != current->has_cpu_usage
        || (
            current->has_cpu_usage
            && metric_changed_points(previous->cpu_usage_percent, current->cpu_usage_percent, config->system_metrics_change_percent)
        )
    ) {
        return 1;
    }
    if (
        metric_changed_points(previous->load_1m_percent, current->load_1m_percent, config->system_metrics_change_percent)
        || metric_changed_points(previous->load_5m_percent, current->load_5m_percent, config->system_metrics_change_percent)
        || metric_changed_points(previous->load_15m_percent, current->load_15m_percent, config->system_metrics_change_percent)
    ) {
        return 1;
    }
    if (previous->has_memory != current->has_memory) {
        return 1;
    }
    if (
        current->has_memory
        && metric_changed_points(previous->memory_usage_percent, current->memory_usage_percent, config->system_metrics_change_percent)
    ) {
        return 1;
    }
    if (previous->has_temperature != current->has_temperature) {
        return 1;
    }
    if (
        current->has_temperature
        && metric_changed_percent(previous->temperature_c, current->temperature_c, config->system_metrics_change_percent)
    ) {
        return 1;
    }
    return 0;
}

static int event_requests_metrics_refresh(const char *event_type)
{
    return strcmp(event_type, "answering_machine.messages_changed") == 0
        || strcmp(event_type, "memos.changed") == 0;
}

static int mqtt_command_is_valid(const char *command)
{
    size_t len = strlen(command);

    if (len < 4 || len >= C300X_MAX_FRAME_LEN || command[0] != '*') {
        return 0;
    }
    if (command[len - 2] != '#' || command[len - 1] != '#') {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        if (!isdigit((unsigned char)command[index]) && command[index] != '*' && command[index] != '#') {
            return 0;
        }
    }
    return 1;
}

static int send_all_bytes(int fd, const char *payload, size_t payload_len)
{
    size_t sent = 0;

    while (sent < payload_len) {
        ssize_t written = send(fd, payload + sent, payload_len - sent, MSG_NOSIGNAL);
        if (written < 0 && errno == EINTR) {
            continue;
        }
        if (written <= 0) {
            return 0;
        }
        sent += (size_t)written;
    }
    return 1;
}

static int send_mqtt_command_to_device(const struct c300x_config *config, const char *command)
{
    char port_text[16];
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    struct addrinfo *item;
    int fd = -1;
    int ok = 0;

    if (!mqtt_command_is_valid(command)) {
        return 0;
    }
    snprintf(port_text, sizeof(port_text), "%u", config->mqtt_command_port);
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(config->mqtt_command_host, port_text, &hints, &result) != 0) {
        return 0;
    }
    for (item = result; item != NULL; item = item->ai_next) {
        fd = socket(item->ai_family, item->ai_socktype, item->ai_protocol);
        if (fd < 0) {
            continue;
        }
        set_socket_timeout(fd, config->openwebnet_timeout_ms);
        if (connect(fd, item->ai_addr, item->ai_addrlen) == 0) {
            ok = send_all_bytes(fd, command, strlen(command)) && send_all_bytes(fd, "\n", 1);
            close(fd);
            break;
        }
        close(fd);
        fd = -1;
    }
    freeaddrinfo(result);
    return ok;
}

static void handle_mqtt_commands(const struct c300x_config *config, struct agent_runtime *runtime)
{
    char command[C300X_MAX_FRAME_LEN];

    while (c300x_mqtt_take_command(&runtime->mqtt, command, sizeof(command))) {
        if (!send_mqtt_command_to_device(config, command)) {
            fprintf(stderr, "mqtt: rejected or failed command\n");
        }
    }
}

static int local_network_online(void)
{
    struct ifaddrs *ifaddr = NULL;
    int online = 0;

    if (getifaddrs(&ifaddr) != 0) {
        return 0;
    }
    for (struct ifaddrs *item = ifaddr; item != NULL; item = item->ifa_next) {
        struct sockaddr_in *addr;
        uint32_t ipv4;
        if (
            item->ifa_addr == NULL
            || item->ifa_addr->sa_family != AF_INET
            || (item->ifa_flags & IFF_UP) == 0
            || (item->ifa_flags & IFF_LOOPBACK) != 0
#ifdef IFF_RUNNING
            || (item->ifa_flags & IFF_RUNNING) == 0
#endif
        ) {
            continue;
        }
        addr = (struct sockaddr_in *)item->ifa_addr;
        ipv4 = ntohl(addr->sin_addr.s_addr);
        if (ipv4 == 0 || (ipv4 & 0xff000000U) == 0x7f000000U || (ipv4 & 0xffff0000U) == 0xa9fe0000U) {
            continue;
        }
        online = 1;
        break;
    }
    freeifaddrs(ifaddr);
    return online;
}

static int runtime_network_online(struct agent_runtime *runtime, time_t now)
{
    int recheck_seconds;

    if (runtime == NULL) {
        return local_network_online();
    }
    recheck_seconds = runtime->network_online
        ? C300X_NETWORK_ONLINE_RECHECK_SECONDS
        : C300X_NETWORK_OFFLINE_RECHECK_SECONDS;
    if (runtime->network_checked_at > 0 && now - runtime->network_checked_at < recheck_seconds) {
        return runtime->network_online;
    }
    runtime->network_online = local_network_online();
    runtime->network_checked_at = now;
    return runtime->network_online;
}

static void system_metrics_init(
    const struct c300x_config *config,
    struct agent_runtime *runtime
)
{
    time_t now = time(NULL);
    if (!system_metrics_watch_active(config, runtime)) {
        runtime->system_metrics_next_sample_at = now + config->system_metrics_heartbeat_seconds;
        return;
    }
    read_system_metrics_sample(&runtime->system_metrics_last, NULL);
    runtime->system_metrics_initialized = 1;
    runtime->system_metrics_dispatched_initialized = 0;
    runtime->system_metrics_last_dispatched_at = 0;
    runtime->system_metrics_next_sample_at = now + config->system_metrics_sample_interval_seconds;
}

static void system_metrics_mark_dispatched(
    struct agent_runtime *runtime,
    const struct system_metrics_sample *sample,
    time_t now
)
{
    runtime->system_metrics_last_dispatched = *sample;
    runtime->system_metrics_dispatched_initialized = 1;
    runtime->system_metrics_last_dispatched_at = now;
}

static void system_metrics_dispatch_now(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    time_t now
)
{
    struct system_metrics_sample sample;
    char metrics_json[2048];
    char data[2300];

    if (!system_metrics_watch_active(config, runtime)) {
        return;
    }
    read_system_metrics_sample(
        &sample,
        runtime->system_metrics_initialized ? &runtime->system_metrics_last : NULL
    );
    runtime->system_metrics_last = sample;
    runtime->system_metrics_initialized = 1;
    runtime->system_metrics_next_sample_at = now + config->system_metrics_sample_interval_seconds;
    if (!system_metrics_json(&sample, 0, metrics_json, sizeof(metrics_json))) {
        return;
    }
    if (snprintf(data, sizeof(data), "{\"system_metrics\":%s}", metrics_json) >= (int)sizeof(data)) {
        return;
    }
    system_metrics_mark_dispatched(runtime, &sample, now);
    dispatch_event(config, runtime, "system.metrics_changed", data, 30);
}

static void system_metrics_dispatch_if_due(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    time_t now
)
{
    struct system_metrics_sample sample;
    char metrics_json[2048];
    char data[2300];
    int heartbeat_due;
    int changed;

    if (!system_metrics_watch_active(config, runtime)) {
        runtime->system_metrics_next_sample_at = now + config->system_metrics_heartbeat_seconds;
        return;
    }
    if (runtime->system_metrics_next_sample_at > now) {
        return;
    }
    runtime->system_metrics_next_sample_at = now + config->system_metrics_sample_interval_seconds;
    read_system_metrics_sample(&sample, runtime->system_metrics_initialized ? &runtime->system_metrics_last : NULL);
    if (!runtime->system_metrics_initialized) {
        runtime->system_metrics_last = sample;
        runtime->system_metrics_initialized = 1;
        return;
    }

    runtime->system_metrics_last = sample;
    heartbeat_due = runtime->system_metrics_last_dispatched_at <= 0
        || now - runtime->system_metrics_last_dispatched_at >= config->system_metrics_heartbeat_seconds;
    changed = !runtime->system_metrics_dispatched_initialized
        || system_metrics_changed(config, &runtime->system_metrics_last_dispatched, &sample);
    if (!heartbeat_due && !changed) {
        return;
    }
    if (!system_metrics_json(&sample, 0, metrics_json, sizeof(metrics_json))) {
        return;
    }
    if (snprintf(data, sizeof(data), "{\"system_metrics\":%s}", metrics_json) >= (int)sizeof(data)) {
        return;
    }
    system_metrics_mark_dispatched(runtime, &sample, now);
    dispatch_event(config, runtime, "system.metrics_changed", data, 30);
}

static int parse_openwebnet_address_event(
    const char *msg,
    const char *prefix,
    char *address,
    size_t address_len
)
{
    size_t prefix_len = strlen(prefix);
    size_t msg_len = strlen(msg);
    size_t value_len;

    if (
        msg_len <= prefix_len + 2
        || strncmp(msg, prefix, prefix_len) != 0
        || strcmp(msg + msg_len - 2, "##") != 0
    ) {
        return 0;
    }
    value_len = msg_len - prefix_len - 2;
    if (value_len == 0 || value_len >= address_len) {
        return 0;
    }
    memcpy(address, msg + prefix_len, value_len);
    address[value_len] = '\0';
    return address_is_valid(address);
}

static int map_openwebnet_event(const char *msg, char *type, size_t type_len, char *data, size_t data_len)
{
    int code;
    char address[C300X_MAX_ADDRESS_LEN];
    char raw_json[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN)];
    char address_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ADDRESS_LEN)];

    if (strlen(msg) >= C300X_MAX_FRAME_LEN) {
        return 0;
    }
    json_string(msg, raw_json, sizeof(raw_json));

    if (sscanf(msg, "*#8**33*%d##", &code) == 1 || sscanf(msg, "*#8**#33*%d##", &code) == 1) {
        snprintf(type, type_len, "%s", code == 0 ? "ringer.muted" : "ringer.unmuted");
        snprintf(data, data_len, "{\"raw\":%s,\"muted\":%s}", raw_json, code == 0 ? "true" : "false");
        return 1;
    }
    if (sscanf(msg, "*#8**37*%d##", &code) == 1 || sscanf(msg, "*#8**#37*%d##", &code) == 1) {
        const char *mode = code == 0 ? "enabled" : (code == 1 ? "in-house-only" : "blocked");
        snprintf(type, type_len, "smartphone_forwarding.changed");
        snprintf(data, data_len, "{\"raw\":%s,\"mode\":\"%s\"}", raw_json, mode);
        return 1;
    }
    if (parse_openwebnet_address_event(msg, "*8*19*", address, sizeof(address))) {
        json_string(address, address_json, sizeof(address_json));
        snprintf(type, type_len, "door_unlock.started");
        snprintf(data, data_len, "{\"raw\":%s,\"address\":%s}", raw_json, address_json);
        return 1;
    }
    if (parse_openwebnet_address_event(msg, "*8*20*", address, sizeof(address))) {
        json_string(address, address_json, sizeof(address_json));
        snprintf(type, type_len, "door_unlock.ended");
        snprintf(data, data_len, "{\"raw\":%s,\"address\":%s}", raw_json, address_json);
        return 1;
    }
    if (parse_openwebnet_address_event(msg, "*8*21*", address, sizeof(address))) {
        json_string(address, address_json, sizeof(address_json));
        snprintf(type, type_len, "stair_light.activated");
        snprintf(data, data_len, "{\"raw\":%s,\"address\":%s}", raw_json, address_json);
        return 1;
    }
    if (strncmp(msg, "*8*1#5#4#", strlen("*8*1#5#4#")) == 0) {
        snprintf(type, type_len, "doorbell.view_requested");
        snprintf(data, data_len, "{\"raw\":%s}", raw_json);
        return 1;
    }
    if (strncmp(msg, "*8*1#1#4#", strlen("*8*1#1#4#")) == 0) {
        snprintf(type, type_len, "doorbell.pressed");
        snprintf(data, data_len, "{\"raw\":%s}", raw_json);
        return 1;
    }
    return 0;
}

static void handle_udp_event(
    int udp_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime
)
{
    unsigned char buffer[2048];
    ssize_t received = recv(udp_fd, buffer, sizeof(buffer), 0);
    int system_end;
    int msg_start;
    int msg_end;
    char system[64];
    char msg[512];
    char type[64];
    char data[768];

    if (received <= 0) {
        return;
    }
    system_end = -1;
    for (int index = 8; index < received; index++) {
        if (buffer[index] == 0) {
            system_end = index;
            break;
        }
    }
    if (system_end < 0 || system_end - 8 >= (int)sizeof(system)) {
        return;
    }
    memcpy(system, buffer + 8, (size_t)(system_end - 8));
    system[system_end - 8] = '\0';
    if (strcmp(system, "OPEN") != 0) {
        return;
    }
    msg_start = system_end + 13;
    if (msg_start >= received) {
        return;
    }
    msg_end = (int)received;
    for (int index = msg_start; index < received; index++) {
        if (buffer[index] == 0) {
            msg_end = index;
            break;
        }
    }
    if (msg_end <= msg_start || msg_end - msg_start >= (int)sizeof(msg)) {
        return;
    }
    memcpy(msg, buffer + msg_start, (size_t)(msg_end - msg_start));
    msg[msg_end - msg_start] = '\0';
    if (map_openwebnet_event(msg, type, sizeof(type), data, sizeof(data))) {
        dispatch_event(config, runtime, type, data, 30);
    }
}

static int join_udp_event_multicast_group(int fd, const struct c300x_config *config)
{
    struct ip_mreq membership;
    struct in_addr group_address;

    memset(&membership, 0, sizeof(membership));
    if (inet_pton(AF_INET, config->events_group, &group_address) != 1) {
        fprintf(stderr, "warning: invalid UDP event multicast group; continuing with bound UDP socket\n");
        return 0;
    }
    membership.imr_multiaddr = group_address;
    membership.imr_interface.s_addr = htonl(INADDR_ANY);
    if (setsockopt(fd, IPPROTO_IP, IP_ADD_MEMBERSHIP, &membership, sizeof(membership)) != 0) {
        fprintf(stderr, "warning: failed to join UDP event multicast group; continuing with bound UDP socket: %s\n", strerror(errno));
        return 0;
    }
    return 1;
}

static int create_udp_event_socket(const struct c300x_config *config)
{
    int fd;
    struct sockaddr_in address;

    if (!config->events_enabled) {
        return -1;
    }
    fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
        return -1;
    }
    set_fd_cloexec(fd);
    allow_socket_reuse(fd);
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    address.sin_port = htons(config->events_port);
    if (bind(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        close(fd);
        return -1;
    }
    (void)join_udp_event_multicast_group(fd, config);
    return fd;
}

static int make_listener(const char *host, uint16_t port)
{
    int fd;
    int is_ipv6 = strchr(host, ':') != NULL;
    int opt = 0;

    fd = socket(is_ipv6 ? AF_INET6 : AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        return -1;
    }
    set_fd_cloexec(fd);
    allow_socket_reuse(fd);
    if (is_ipv6) {
        struct sockaddr_in6 address6;
        memset(&address6, 0, sizeof(address6));
        address6.sin6_family = AF_INET6;
        address6.sin6_port = htons(port);
        if (inet_pton(AF_INET6, host, &address6.sin6_addr) != 1) {
            close(fd);
            return -1;
        }
        (void)setsockopt(fd, IPPROTO_IPV6, IPV6_V6ONLY, &opt, sizeof(opt));
        if (bind(fd, (struct sockaddr *)&address6, sizeof(address6)) != 0) {
            close(fd);
            return -1;
        }
    } else {
        struct sockaddr_in address;
        memset(&address, 0, sizeof(address));
        address.sin_family = AF_INET;
        address.sin_port = htons(port);
        if (inet_pton(AF_INET, host, &address.sin_addr) != 1) {
            close(fd);
            return -1;
        }
        if (bind(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
            close(fd);
            return -1;
        }
    }
    if (listen(fd, 8) != 0) {
        close(fd);
        return -1;
    }
    set_fd_nonblocking(fd);
    return fd;
}

static void send_response(
    int client_fd,
    int status,
    const char *reason,
    const char *body,
    const char *extra_headers
)
{
    char header[1024];
    size_t body_len = strlen(body);
    int header_len = snprintf(
        header,
        sizeof(header),
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %zu\r\n"
        "Connection: close\r\n"
        "%s"
        "\r\n",
        status,
        reason,
        body_len,
        extra_headers != NULL ? extra_headers : ""
    );

    if (header_len > 0) {
        (void)send(client_fd, header, (size_t)header_len, MSG_NOSIGNAL);
    }
    (void)send(client_fd, body, body_len, MSG_NOSIGNAL);
}

static void send_json(int client_fd, int status, const char *reason, const char *body)
{
    send_response(client_fd, status, reason, body, NULL);
}

static void send_file_response(
    int client_fd,
    const char *path,
    const char *content_type,
    const char *cache_control
)
{
    FILE *file;
    char header[1024];
    unsigned char buffer[8192];
    int header_len;
    long file_size;

    file = fopen(path, "rb");
    if (file == NULL) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"media_not_found\"}\n");
        return;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"media_not_found\"}\n");
        return;
    }
    file_size = ftell(file);
    if (file_size < 0 || fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"media_not_found\"}\n");
        return;
    }
    header_len = snprintf(
        header,
        sizeof(header),
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %lld\r\n"
        "Cache-Control: %s\r\n"
        "Connection: close\r\n"
        "\r\n",
        content_type != NULL ? content_type : "application/octet-stream",
        (long long)file_size,
        cache_control != NULL ? cache_control : "no-store"
    );
    if (header_len > 0) {
        (void)send(client_fd, header, (size_t)header_len, MSG_NOSIGNAL);
    }
    for (;;) {
        size_t read_len = fread(buffer, 1, sizeof(buffer), file);
        if (read_len > 0 && send(client_fd, buffer, read_len, MSG_NOSIGNAL) < 0) {
            break;
        }
        if (read_len < sizeof(buffer)) {
            break;
        }
    }
    fclose(file);
}

static void send_auth_required(int client_fd)
{
    send_response(
        client_fd,
        401,
        "Unauthorized",
        "{\"ok\":false,\"error\":\"unauthorized\"}\n",
        "WWW-Authenticate: Bearer\r\n"
    );
}

static int constant_time_equal(const char *left, size_t left_len, const char *right)
{
    size_t right_len = strlen(right);
    size_t max_len = left_len > right_len ? left_len : right_len;
    unsigned char diff = (unsigned char)(left_len ^ right_len);
    size_t index;

    for (index = 0; index < max_len; index++) {
        unsigned char left_ch = index < left_len ? (unsigned char)left[index] : 0;
        unsigned char right_ch = index < right_len ? (unsigned char)right[index] : 0;
        diff |= (unsigned char)(left_ch ^ right_ch);
    }
    return diff == 0;
}

static int has_valid_bearer(const struct request *request, const char *token)
{
    const char *line = request->headers;
    const size_t prefix_len = strlen("authorization:");

    if (token == NULL || token[0] == '\0') {
        return 0;
    }
    while (*line != '\0') {
        const char *line_end = strstr(line, "\r\n");
        const char *value;
        const char *token_start;
        size_t token_len;

        if (line_end == NULL) {
            line_end = line + strlen(line);
        }
        if ((size_t)(line_end - line) > prefix_len && strncasecmp(line, "authorization:", prefix_len) == 0) {
            value = line + prefix_len;
            while (value < line_end && (*value == ' ' || *value == '\t')) {
                value++;
            }
            if ((size_t)(line_end - value) < 7 || strncasecmp(value, "Bearer ", 7) != 0) {
                return 0;
            }
            token_start = value + 7;
            while (token_start < line_end && (*token_start == ' ' || *token_start == '\t')) {
                token_start++;
            }
            token_len = (size_t)(line_end - token_start);
            while (token_len > 0 && (token_start[token_len - 1] == ' ' || token_start[token_len - 1] == '\t')) {
                token_len--;
            }
            return constant_time_equal(token_start, token_len, token);
        }
        if (*line_end == '\0') {
            break;
        }
        line = line_end + 2;
    }
    return 0;
}

static int api_request_authorized(const struct c300x_config *config, const struct request *request)
{
    return config->api_no_auth || has_valid_bearer(request, config->api_token);
}

static int parse_request(char *buffer, struct request *request)
{
    char *line_end;
    char *header_end;
    char *headers_start;
    char *line_path;

    memset(request, 0, sizeof(*request));
    line_end = strstr(buffer, "\r\n");
    if (line_end == NULL) {
        return 0;
    }
    *line_end = '\0';
    line_path = request->path;
    if (sscanf(buffer, "%7s %255s", request->method, line_path) != 2) {
        return 0;
    }
    request_path_and_query(line_path, request->path, sizeof(request->path), request->query, sizeof(request->query));
    headers_start = line_end + 2;
    header_end = strstr(headers_start, "\r\n\r\n");
    if (header_end == NULL) {
        return 0;
    }
    *header_end = '\0';
    snprintf(request->headers, sizeof(request->headers), "%s", headers_start);
    snprintf(request->body, sizeof(request->body), "%s", header_end + 4);
    request->body_len = strlen(request->body);
    return 1;
}

static size_t content_length_from_buffer(const char *buffer, const char *header_end)
{
    const char *line = strstr(buffer, "\r\n");

    if (line == NULL || line >= header_end) {
        return 0;
    }
    line += 2;
    while (line < header_end) {
        const char *line_end = strstr(line, "\r\n");
        const char *value;
        char *endptr;
        unsigned long parsed;

        if (line_end == NULL || line_end > header_end) {
            line_end = header_end;
        }
        if (
            (size_t)(line_end - line) > strlen("content-length:")
            && strncasecmp(line, "content-length:", strlen("content-length:")) == 0
        ) {
            value = line + strlen("content-length:");
            while (value < line_end && (*value == ' ' || *value == '\t')) {
                value++;
            }
            errno = 0;
            parsed = strtoul(value, &endptr, 10);
            if (errno != 0 || endptr == value) {
                return 0;
            }
            if (parsed > REQUEST_BUFFER_SIZE) {
                return REQUEST_BUFFER_SIZE;
            }
            return (size_t)parsed;
        }
        if (line_end >= header_end) {
            break;
        }
        line = line_end + 2;
    }
    return 0;
}

static int receive_http_request(int client_fd, char *buffer, size_t buffer_len, int *too_large)
{
    size_t used = 0;

    *too_large = 0;
    while (used + 1 < buffer_len) {
        ssize_t received = recv(client_fd, buffer + used, buffer_len - used - 1, 0);
        char *header_end;
        size_t header_len;
        size_t content_len;

        if (received <= 0) {
            return used > 0 ? 1 : 0;
        }
        used += (size_t)received;
        buffer[used] = '\0';
        header_end = strstr(buffer, "\r\n\r\n");
        if (header_end == NULL) {
            continue;
        }
        header_len = (size_t)(header_end + 4 - buffer);
        content_len = content_length_from_buffer(buffer, header_end);
        if (content_len > buffer_len - header_len - 1) {
            *too_large = 1;
            return 0;
        }
        if (used >= header_len + content_len) {
            return 1;
        }
    }
    *too_large = 1;
    return 0;
}

static void api_capabilities(int client_fd, const struct c300x_config *config)
{
    char body[8192];
    char video_path[C300X_MAX_PATH_JSON_LEN];
    char audio_path[C300X_MAX_PATH_JSON_LEN];
    char recorder_path[C300X_MAX_PATH_JSON_LEN];
    char device_id[64];
    char device_id_json[128];
    char device_model[128];
    char device_firmware[384];
    char stair_address[128];
    char lock_id[128];
    char lock_name[384];
    char bundle_hash[C300X_AGENT_BUNDLE_HASH_LEN];
    char bundle_hash_json[C300X_JSON_QUOTED_LEN(C300X_AGENT_BUNDLE_HASH_LEN)];
    char bundle_agent_version[C300X_MAX_VERSION_LEN];
    char bundle_api_version[16];
    int maintenance_supported = maintenance_auth_available(config);

    c300x_mdns_device_id(device_id, sizeof(device_id));
    (void)read_agent_bundle_metadata(
        config,
        bundle_hash,
        sizeof(bundle_hash),
        bundle_agent_version,
        sizeof(bundle_agent_version),
        bundle_api_version,
        sizeof(bundle_api_version)
    );
    json_escape_string(device_id, device_id_json, sizeof(device_id_json));
    json_escape_string(config->video_rtsp_video_path, video_path, sizeof(video_path));
    json_escape_string(config->video_rtsp_path, audio_path, sizeof(audio_path));
    json_escape_string(config->video_rtsp_recorder_path, recorder_path, sizeof(recorder_path));
    json_escape_string(config->device_model, device_model, sizeof(device_model));
    json_escape_string(config->device_firmware, device_firmware, sizeof(device_firmware));
    json_escape_string(config->stair_light_default_address, stair_address, sizeof(stair_address));
    json_escape_string(config->lock_id, lock_id, sizeof(lock_id));
    json_escape_string(config->lock_name, lock_name, sizeof(lock_name));
    json_string(bundle_hash, bundle_hash_json, sizeof(bundle_hash_json));
    snprintf(
        body,
        sizeof(body),
        "{"
        "\"api_version\":\"1\","
        "\"agent\":{\"implementation\":\"native-c\",\"version\":\"%s\",\"api_version\":\"1\",\"bundle_hash\":%s,\"self_update_supported\":%s},"
        "\"device\":{\"id\":\"%s\",\"model\":\"%s\",\"firmware\":\"%s\"},"
        "\"capabilities\":{"
        "\"doorbell_events\":true,"
        "\"doorbell_video\":{\"supported\":%s,\"stream_path\":\"%s\",\"audio_stream_path\":\"%s\",\"recorder_stream_path\":\"%s\",\"audio_codec\":\"%s\",\"talkback_supported\":true,\"talkback_codec\":\"%s\",\"talkback_payload_type\":%d},"
        "\"stair_light\":{\"supported\":true,\"default_address\":\"%s\"},"
        "\"locks\":{\"supported\":true,\"default_id\":\"%s\",\"locks\":[{\"id\":\"%s\",\"name\":\"%s\"}]},"
        "\"call_events\":false,"
        "\"ringer\":true,"
        "\"smartphone_forwarding\":{\"supported\":true,\"modes\":[\"enabled\",\"in-house-only\",\"blocked\"]},"
        "\"answering_machine\":{\"supported\":true,\"status\":true,\"greeting_message\":true,\"messages\":{\"supported\":%s,\"source\":\"local_files\",\"watch\":%s,\"media\":%s,\"delete\":%s}},"
        "\"memos\":{\"supported\":%s,\"text\":true,\"voice\":true,\"media\":%s,\"source\":\"local_files\",\"watch\":%s,\"delete\":%s},"
        "\"system_metrics\":{\"supported\":%s,\"cpu\":true,\"load\":true,\"memory\":true,\"temperature\":true,\"watch\":%s,\"sample_interval_seconds\":%d,\"heartbeat_seconds\":%d,\"change_percent\":%d},"
        "\"mqtt\":{\"supported\":true,\"enabled\":%s,\"configured\":%s},"
        "\"diagnostics\":{\"supported\":true,\"writes\":true,\"runtime\":true},"
        "\"auth\":{\"supported\":true,\"configurable\":true,\"no_auth\":%s,\"api_token_configured\":%s,\"maintenance_token_configured\":%s},"
        "\"maintenance\":{\"supported\":%s,\"ssh_start\":%s,\"ssh_stop\":%s,\"ssh_status\":%s,\"reboot\":%s,\"agent_remove\":%s,\"agent_update\":%s,\"config_normalize\":%s,\"mqtt_status\":%s,\"mqtt_config\":%s,\"legacy_mqtt_status\":%s,\"legacy_mqtt_config\":%s,\"legacy_mqtt_migrate\":%s,\"gui_reload\":%s,\"firewall_status\":%s,\"firewall_apply\":%s,\"firewall_restore\":%s,\"ipv6_firewall_status\":%s,\"ipv6_firewall_apply\":%s,\"ipv6_firewall_restore\":%s,\"qml_status\":%s,\"qml_patch\":%s,\"qml_restore\":%s},"
        "\"display_bridge\":{\"supported\":true,\"configurable\":true,\"configured\":%s}"
        "}"
        "}\n",
        C300X_NATIVE_AGENT_VERSION,
        bundle_hash_json,
        maintenance_supported ? "true" : "false",
        device_id_json,
        device_model,
        device_firmware,
        config->video_enabled ? "true" : "false",
        video_path,
        audio_path,
        recorder_path,
        C300X_TALKBACK_CODEC,
        C300X_TALKBACK_CODEC,
        C300X_TALKBACK_RTP_PAYLOAD_TYPE,
        stair_address,
        lock_id,
        lock_id,
        lock_name,
        config->answering_machine_messages_enabled ? "true" : "false",
        (config->answering_machine_messages_enabled && config->answering_machine_messages_watch) ? "true" : "false",
        config->answering_machine_messages_enabled ? "true" : "false",
        config->answering_machine_messages_enabled ? "true" : "false",
        config->memos_enabled ? "true" : "false",
        config->memos_enabled ? "true" : "false",
        (config->memos_enabled && config->memos_watch) ? "true" : "false",
        config->memos_enabled ? "true" : "false",
        config->system_metrics_enabled ? "true" : "false",
        (config->system_metrics_enabled && config->system_metrics_watch) ? "true" : "false",
        config->system_metrics_sample_interval_seconds,
        config->system_metrics_heartbeat_seconds,
        config->system_metrics_change_percent,
        config->mqtt_enabled ? "true" : "false",
        config->mqtt_host[0] != '\0' ? "true" : "false",
        config->api_no_auth ? "true" : "false",
        config->api_token[0] != '\0' ? "true" : "false",
        config->maintenance_admin_token[0] != '\0' ? "true" : "false",
        maintenance_supported ? "true" : "false",
        (maintenance_supported && config->maintenance_ssh_start_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_ssh_start_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_ssh_start_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_reboot_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_agent_remove_enabled) ? "true" : "false",
        maintenance_supported ? "true" : "false",
        maintenance_supported ? "true" : "false",
        maintenance_supported ? "true" : "false",
        maintenance_supported ? "true" : "false",
        maintenance_supported ? "true" : "false",
        maintenance_supported ? "true" : "false",
        maintenance_supported ? "true" : "false",
        (maintenance_supported && config->maintenance_gui_reload_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_firewall_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_firewall_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_firewall_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_ipv6_firewall_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_ipv6_firewall_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_ipv6_firewall_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_qml_patch_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_qml_patch_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_qml_patch_enabled) ? "true" : "false",
        config->display_bridge_enabled ? "true" : "false"
    );
    send_json(client_fd, 200, "OK", body);
}

static void api_state(
    int client_fd,
    const struct c300x_config *config,
    const struct agent_runtime *runtime
)
{
    char body[2048];
    char video_path_escaped[C300X_MAX_PATH_JSON_LEN];
    struct c300x_video_status video_status;
    int video_available = 0;
    const char *video_path = NULL;

    if (runtime != NULL && runtime->video != NULL) {
        c300x_video_status(runtime->video, &video_status);
        video_available = video_status.enabled;
    }
    if (config->video_enabled) {
        video_path = config->video_rtsp_video_path;
    }

    if (video_path != NULL) {
        json_escape_string(video_path, video_path_escaped, sizeof(video_path_escaped));
        snprintf(
            body,
            sizeof(body),
            "{"
            "\"state\":{"
            "\"doorbell\":\"idle\","
            "\"video_available\":%s,"
            "\"video_stream_path\":\"%s\","
            "\"smartphone_forwarding\":null,"
            "\"ringer_muted\":null,"
            "\"answering_machine_enabled\":null"
            "}"
            "}\n",
            video_available ? "true" : "false",
            video_path_escaped
        );
    } else {
        snprintf(
            body,
            sizeof(body),
            "{"
            "\"state\":{"
            "\"doorbell\":\"idle\","
            "\"video_available\":false,"
            "\"video_stream_path\":null,"
            "\"smartphone_forwarding\":null,"
            "\"ringer_muted\":null,"
            "\"answering_machine_enabled\":null"
            "}"
            "}\n"
        );
    }
    send_json(client_fd, 200, "OK", body);
}

static void handle_doorbell_video_get(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime
)
{
    enum { VIDEO_STATUS_BODY_LEN = 12288 };
    char *body = malloc(VIDEO_STATUS_BODY_LEN);
    struct c300x_video_status video_status;
    int running = 0;
    int call_active = 0;
    int clients = 0;
    int media_starting = 0;
    int stream_audio = 0;
    int talkback_running = 0;
    int bridge_running = 0;
    int bridge_media_active = 0;
    int bridge_stop_in_progress = 0;
    int bridge_open_fds = 0;
    int bridge_active_threads = 0;
    unsigned long long rtp_packets = 0;
    const char *last_rtp_at_json = "null";
    const char *last_media_started_at_json = "null";
    const char *last_error_json = "null";
    char stream_path[C300X_MAX_PATH_JSON_LEN];
    char audio_stream_path[C300X_MAX_PATH_JSON_LEN];
    char recorder_stream_path[C300X_MAX_PATH_JSON_LEN];
    char last_rtp_at_quoted[96];
    char last_media_started_at_quoted[96];
    char last_error_quoted[(C300X_MAX_ERROR_LEN * 6) + 3];

    if (body == NULL) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        return;
    }
    if (runtime != NULL && runtime->video != NULL) {
        c300x_video_status(runtime->video, &video_status);
        running = video_status.running;
        call_active = video_status.call_active;
        clients = video_status.clients;
        media_starting = video_status.media_starting;
        stream_audio = video_status.stream_audio;
        talkback_running = video_status.talkback_running;
        bridge_running = video_status.bridge_running;
        bridge_media_active = video_status.bridge_media_active;
        bridge_stop_in_progress = video_status.bridge_stop_in_progress;
        bridge_open_fds = video_status.bridge_open_fds;
        bridge_active_threads = video_status.bridge_active_threads;
        rtp_packets = video_status.rtp_packets;
        last_rtp_at_json = json_string_or_null(
            video_status.last_rtp_at,
            last_rtp_at_quoted,
            sizeof(last_rtp_at_quoted)
        );
        last_media_started_at_json = json_string_or_null(
            video_status.last_media_started_at,
            last_media_started_at_quoted,
            sizeof(last_media_started_at_quoted)
        );
        last_error_json = json_string_or_null(
            video_status.last_error,
            last_error_quoted,
            sizeof(last_error_quoted)
        );
    }
    json_escape_string(config->video_rtsp_video_path, stream_path, sizeof(stream_path));
    json_escape_string(config->video_rtsp_path, audio_stream_path, sizeof(audio_stream_path));
    json_escape_string(config->video_rtsp_recorder_path, recorder_stream_path, sizeof(recorder_stream_path));
    snprintf(
        body,
        VIDEO_STATUS_BODY_LEN,
        "{"
        "\"ok\":true,"
        "\"available\":%s,"
        "\"window_available\":false,"
        "\"active_until\":null,"
        "\"stream_path\":\"%s\","
        "\"audio_stream_path\":\"%s\","
        "\"recorder_stream_path\":\"%s\","
        "\"bridge\":{"
        "\"enabled\":%s,"
        "\"running\":%s,"
        "\"bridge_running\":%s,"
        "\"media_active\":%s,"
        "\"stop_in_progress\":%s,"
        "\"open_fds\":%d,"
        "\"active_threads\":%d,"
        "\"call_active\":%s,"
        "\"clients\":%d,"
        "\"media_starting\":%s,"
        "\"audio_enabled\":%s,"
        "\"rtp_packets\":%llu,"
        "\"last_rtp_at\":%s,"
        "\"last_media_started_at\":%s,"
        "\"last_error\":%s,"
        "\"stream_path\":\"%s\","
        "\"audio_stream_path\":\"%s\","
        "\"recorder_stream_path\":\"%s\","
        "\"audio_codec\":\"%s\","
        "\"talkback_supported\":true,"
        "\"talkback_running\":%s,"
        "\"talkback_port\":%d,"
        "\"talkback_payload_type\":%d,"
        "\"talkback_codec\":\"%s\","
        "\"video_codec\":\"H264/90000\","
        "\"video_profile_level_id\":\"42401E\""
        "}"
        "}\n",
        config->video_enabled ? "true" : "false",
        stream_path,
        audio_stream_path,
        recorder_stream_path,
        config->video_enabled ? "true" : "false",
        running ? "true" : "false",
        bridge_running ? "true" : "false",
        bridge_media_active ? "true" : "false",
        bridge_stop_in_progress ? "true" : "false",
        bridge_open_fds,
        bridge_active_threads,
        call_active ? "true" : "false",
        clients,
        media_starting ? "true" : "false",
        stream_audio ? "true" : "false",
        rtp_packets,
        last_rtp_at_json,
        last_media_started_at_json,
        last_error_json,
        stream_path,
        audio_stream_path,
        recorder_stream_path,
        C300X_TALKBACK_CODEC,
        talkback_running ? "true" : "false",
        C300X_TALKBACK_RTP_PORT,
        C300X_TALKBACK_RTP_PAYLOAD_TYPE,
        C300X_TALKBACK_CODEC
    );
    send_json(client_fd, 200, "OK", body);
    free(body);
}

static void handle_doorbell_video_activate(
    int client_fd,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    int audio = 1;
    char body[2048];
    char last_error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];

    if (runtime == NULL || runtime->video == NULL) {
        send_json(client_fd, 503, "Service Unavailable", "{\"ok\":false,\"error\":\"video_unavailable\"}\n");
        return;
    }
    (void)json_bool_field(request->body, "audio", &audio);
    if (!c300x_video_activate(runtime->video, audio)) {
        struct c300x_video_status status;
        c300x_video_status(runtime->video, &status);
        json_string(
            status.last_error[0] != '\0' ? status.last_error : "unknown",
            last_error_json,
            sizeof(last_error_json)
        );
        snprintf(
            body,
            sizeof(body),
            "{\"ok\":false,\"error\":\"video_activate_failed\",\"last_error\":%s}\n",
            last_error_json
        );
        send_json(client_fd, 503, "Service Unavailable", body);
        return;
    }
    snprintf(body, sizeof(body), "{\"ok\":true,\"audio\":%s}\n", audio ? "true" : "false");
    send_json(client_fd, 200, "OK", body);
}

static void handle_doorbell_video_stop(int client_fd, struct agent_runtime *runtime)
{
    if (runtime != NULL && runtime->video != NULL) {
        c300x_video_stop(runtime->video);
    }
    send_json(client_fd, 200, "OK", "{\"ok\":true}\n");
}

static double read_temperature_c(const char **source)
{
    const char *paths[] = {
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/devices/virtual/thermal/thermal_zone0/temp",
        NULL,
    };
    for (size_t index = 0; paths[index] != NULL; index++) {
        FILE *file = fopen(paths[index], "r");
        double value;
        if (file == NULL) {
            continue;
        }
        if (fscanf(file, "%lf", &value) == 1) {
            fclose(file);
            *source = paths[index];
            if (value > 1000.0 || value < -1000.0) {
                value /= 1000.0;
            }
            return value;
        }
        fclose(file);
    }
    *source = NULL;
    return -100000.0;
}

static long online_cpu_count(void)
{
    long count = sysconf(_SC_NPROCESSORS_ONLN);
    return count > 0 ? count : 1;
}

static double load_percent(double load_average, long cpu_count)
{
    if (cpu_count <= 0 || load_average < 0.0) {
        return 0.0;
    }
    return (load_average / (double)cpu_count) * 100.0;
}

static int read_cpu_jiffies(unsigned long long *total, unsigned long long *idle)
{
    FILE *file = fopen("/proc/stat", "r");
    char label[8];
    unsigned long long user;
    unsigned long long nice;
    unsigned long long system;
    unsigned long long idle_time;
    unsigned long long iowait;
    unsigned long long irq;
    unsigned long long softirq;
    unsigned long long steal;
    int fields;

    if (file == NULL) {
        return 0;
    }
    fields = fscanf(
        file,
        "%7s %llu %llu %llu %llu %llu %llu %llu %llu",
        label,
        &user,
        &nice,
        &system,
        &idle_time,
        &iowait,
        &irq,
        &softirq,
        &steal
    );
    fclose(file);
    if (fields < 5 || strcmp(label, "cpu") != 0) {
        return 0;
    }
    if (fields < 6) {
        iowait = 0;
    }
    if (fields < 7) {
        irq = 0;
    }
    if (fields < 8) {
        softirq = 0;
    }
    if (fields < 9) {
        steal = 0;
    }
    *idle = idle_time + iowait;
    *total = user + nice + system + idle_time + iowait + irq + softirq + steal;
    return *total > 0;
}

static int read_memory_metrics(
    long *total_kb,
    long *available_kb,
    long *used_kb,
    double *usage_percent
)
{
    FILE *file = fopen("/proc/meminfo", "r");
    char line[160];
    long total = -1;
    long available = -1;
    long free_kb = 0;
    long buffers = 0;
    long cached = 0;
    long reclaimable = 0;

    if (file == NULL) {
        return 0;
    }
    while (fgets(line, sizeof(line), file) != NULL) {
        char key[64];
        char unit[16];
        long value;

        if (sscanf(line, "%63s %ld %15s", key, &value, unit) < 2) {
            continue;
        }
        if (strcmp(key, "MemTotal:") == 0) {
            total = value;
        } else if (strcmp(key, "MemAvailable:") == 0) {
            available = value;
        } else if (strcmp(key, "MemFree:") == 0) {
            free_kb = value;
        } else if (strcmp(key, "Buffers:") == 0) {
            buffers = value;
        } else if (strcmp(key, "Cached:") == 0) {
            cached = value;
        } else if (strcmp(key, "SReclaimable:") == 0) {
            reclaimable = value;
        }
    }
    fclose(file);
    if (total <= 0) {
        return 0;
    }
    if (available < 0) {
        available = free_kb + buffers + cached + reclaimable;
    }
    if (available < 0) {
        available = 0;
    }
    if (available > total) {
        available = total;
    }
    *total_kb = total;
    *available_kb = available;
    *used_kb = total - available;
    *usage_percent = ((double)*used_kb / (double)total) * 100.0;
    return 1;
}

static double double_abs(double value)
{
    return value < 0.0 ? -value : value;
}

static int metric_changed_percent(double previous, double current, int threshold_percent)
{
    double threshold = (double)threshold_percent;
    double diff = double_abs(current - previous);
    double baseline = double_abs(previous);

    if (threshold_percent <= 0) {
        return diff > 0.0;
    }
    if (baseline < 0.001) {
        return diff >= threshold;
    }
    return ((diff / baseline) * 100.0) >= threshold;
}

static int metric_changed_points(double previous, double current, int threshold_points)
{
    double threshold = (double)threshold_points;
    double diff = double_abs(current - previous);

    if (threshold_points <= 0) {
        return diff > 0.0;
    }
    return diff >= threshold;
}

static int read_system_metrics_sample(
    struct system_metrics_sample *sample,
    const struct system_metrics_sample *previous
)
{
    double loads[3] = {0.0, 0.0, 0.0};
    double temperature;
    const char *temperature_source = NULL;
    FILE *load_file;

    memset(sample, 0, sizeof(*sample));
    load_file = fopen("/proc/loadavg", "r");
    if (load_file != NULL) {
        if (fscanf(load_file, "%lf %lf %lf", &loads[0], &loads[1], &loads[2]) != 3) {
            loads[0] = 0.0;
            loads[1] = 0.0;
            loads[2] = 0.0;
        }
        fclose(load_file);
    }
    sample->cpu_count = online_cpu_count();
    if (read_cpu_jiffies(&sample->cpu_total_jiffies, &sample->cpu_idle_jiffies)) {
        sample->has_cpu_jiffies = 1;
        if (
            previous != NULL
            && previous->has_cpu_jiffies
            && sample->cpu_total_jiffies > previous->cpu_total_jiffies
            && sample->cpu_idle_jiffies >= previous->cpu_idle_jiffies
        ) {
            unsigned long long total_delta = sample->cpu_total_jiffies - previous->cpu_total_jiffies;
            unsigned long long idle_delta = sample->cpu_idle_jiffies - previous->cpu_idle_jiffies;
            if (total_delta > 0 && idle_delta <= total_delta) {
                sample->cpu_usage_percent = ((double)(total_delta - idle_delta) / (double)total_delta) * 100.0;
                sample->has_cpu_usage = 1;
            }
        }
    }
    sample->load_1m = loads[0];
    sample->load_5m = loads[1];
    sample->load_15m = loads[2];
    sample->load_1m_percent = load_percent(loads[0], sample->cpu_count);
    sample->load_5m_percent = load_percent(loads[1], sample->cpu_count);
    sample->load_15m_percent = load_percent(loads[2], sample->cpu_count);
    if (read_memory_metrics(
        &sample->memory_total_kb,
        &sample->memory_available_kb,
        &sample->memory_used_kb,
        &sample->memory_usage_percent
    )) {
        sample->has_memory = 1;
    }
    temperature = read_temperature_c(&temperature_source);
    if (temperature_source != NULL) {
        sample->has_temperature = 1;
        sample->temperature_c = temperature;
        snprintf(sample->temperature_source, sizeof(sample->temperature_source), "%s", temperature_source);
    }
    return 1;
}

static int system_metrics_json(
    const struct system_metrics_sample *sample,
    int include_ok,
    char *body,
    size_t body_len
)
{
    const char *prefix = include_ok ? "{\"ok\":true," : "{";
    char cpu_usage_json[32];
    char memory_json[192];
    char temperature_json[768];
    int written;

    if (sample->has_cpu_usage) {
        snprintf(cpu_usage_json, sizeof(cpu_usage_json), "%.1f", sample->cpu_usage_percent);
    } else {
        snprintf(cpu_usage_json, sizeof(cpu_usage_json), "null");
    }
    if (sample->has_memory) {
        snprintf(
            memory_json,
            sizeof(memory_json),
            "\"memory_total_kb\":%ld,\"memory_available_kb\":%ld,\"memory_used_kb\":%ld,\"memory_usage_percent\":%.1f",
            sample->memory_total_kb,
            sample->memory_available_kb,
            sample->memory_used_kb,
            sample->memory_usage_percent
        );
    } else {
        snprintf(
            memory_json,
            sizeof(memory_json),
            "\"memory_total_kb\":null,\"memory_available_kb\":null,\"memory_used_kb\":null,\"memory_usage_percent\":null"
        );
    }
    if (sample->has_temperature) {
        snprintf(
            temperature_json,
            sizeof(temperature_json),
            "\"temperature_c\":%.1f,\"temperature_source\":\"%s\"",
            sample->temperature_c,
            sample->temperature_source
        );
    } else {
        snprintf(
            temperature_json,
            sizeof(temperature_json),
            "\"temperature_c\":null,\"temperature_source\":null"
        );
    }
    written = snprintf(
        body,
        body_len,
        "%s\"cpu_count\":%ld,\"cpu_usage_percent\":%s,\"load_1m\":%.2f,\"load_5m\":%.2f,\"load_15m\":%.2f,\"load_1m_percent\":%.1f,\"load_5m_percent\":%.1f,\"load_15m_percent\":%.1f,%s,%s}",
        prefix,
        sample->cpu_count,
        cpu_usage_json,
        sample->load_1m,
        sample->load_5m,
        sample->load_15m,
        sample->load_1m_percent,
        sample->load_5m_percent,
        sample->load_15m_percent,
        memory_json,
        temperature_json
    );
    return written > 0 && (size_t)written < body_len;
}

static void handle_system_metrics(int client_fd, const struct agent_runtime *runtime)
{
    struct system_metrics_sample sample;
    char body[2048];

    read_system_metrics_sample(
        &sample,
        runtime != NULL && runtime->system_metrics_initialized ? &runtime->system_metrics_last : NULL
    );
    if (!system_metrics_json(&sample, 1, body, sizeof(body))) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        return;
    }
    strncat(body, "\n", sizeof(body) - strlen(body) - 1);
    send_json(client_fd, 200, "OK", body);
}

static const char *smartphone_mode_from_reply(const char *reply)
{
    if (strcmp(reply, "*#8**37*0##") == 0 || strcmp(reply, "*#8**#37*0##") == 0) {
        return "enabled";
    }
    if (strcmp(reply, "*#8**37*1##") == 0 || strcmp(reply, "*#8**#37*1##") == 0) {
        return "in-house-only";
    }
    if (strcmp(reply, "*#8**37*2##") == 0 || strcmp(reply, "*#8**#37*2##") == 0) {
        return "blocked";
    }
    return NULL;
}

static int ringer_muted_from_reply(const char *reply, int *muted)
{
    if (strcmp(reply, "*#8**33*0##") == 0 || strcmp(reply, "*#8**#33*0##") == 0) {
        *muted = 1;
        return 1;
    }
    if (strcmp(reply, "*#8**33*1##") == 0 || strcmp(reply, "*#8**#33*1##") == 0) {
        *muted = 0;
        return 1;
    }
    return 0;
}

static int answering_enabled_from_reply(const char *reply, int fallback, int *enabled, int *greeting)
{
    const char *prefix = "*#8**40*";

    if (strncmp(reply, prefix, strlen(prefix)) == 0 && strlen(reply) >= strlen(prefix) + 5) {
        const char *ptr = reply + strlen(prefix);
        if ((ptr[0] == '0' || ptr[0] == '1') && ptr[1] == '*' && (ptr[2] == '0' || ptr[2] == '1')) {
            *enabled = ptr[0] == '1';
            *greeting = ptr[2] == '1';
            return 1;
        }
    }
    if (strcmp(reply, "*#*1##") == 0 && fallback >= 0) {
        *enabled = fallback;
        *greeting = -1;
        return 1;
    }
    return 0;
}

static void send_device_error(int client_fd, const char *error)
{
    char body[2048];
    char error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];
    json_string(error, error_json, sizeof(error_json));
    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":%s}\n", error_json);
    send_json(client_fd, 502, "Bad Gateway", body);
}

static int activate_stair_light(
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    char *address,
    size_t address_len,
    char *reply,
    size_t reply_len,
    char *error,
    size_t error_len
)
{
    char command[64];
    char event_data[128];
    char address_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ADDRESS_LEN)];

    if (address[0] == '\0') {
        snprintf(address, address_len, "%s", config->stair_light_default_address);
    }
    if (!address_is_valid(address)) {
        snprintf(error, error_len, "invalid_stair_light_address");
        return 0;
    }
    snprintf(command, sizeof(command), "*8*21*%s##", address);
    if (!c300x_openwebnet_send(config, command, reply, reply_len, error, error_len)) {
        return 0;
    }
    if (runtime != NULL) {
        json_string(address, address_json, sizeof(address_json));
        if (snprintf(event_data, sizeof(event_data), "{\"address\":%s}", address_json) < (int)sizeof(event_data)) {
            dispatch_event(config, runtime, "stair_light.activated", event_data, 0);
        }
    }
    return 1;
}

static void handle_stair_light(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    char address[C300X_MAX_ADDRESS_LEN];
    char reply[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    char body[2048];
    char address_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ADDRESS_LEN)];
    char reply_json[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN)];

    json_string_field(request->body, "address", address, sizeof(address));
    if (!activate_stair_light(
        config,
        runtime,
        address,
        sizeof(address),
        reply,
        sizeof(reply),
        error,
        sizeof(error)
    )) {
        if (strcmp(error, "invalid_stair_light_address") == 0) {
            send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_stair_light_address\"}\n");
            return;
        }
        send_device_error(client_fd, error);
        return;
    }
    json_string(address, address_json, sizeof(address_json));
    json_string(reply, reply_json, sizeof(reply_json));
    snprintf(body, sizeof(body), "{\"ok\":true,\"address\":%s,\"raw\":%s}\n", address_json, reply_json);
    send_json(client_fd, 200, "OK", body);
}

static void handle_unlock(
    int client_fd,
    const struct c300x_config *config,
    const char *lock_id
)
{
    char press[64];
    char release[64];
    char error[C300X_MAX_ERROR_LEN];
    char body[1024];
    char lock_id_json[C300X_JSON_QUOTED_LEN(C300X_MAX_LOCK_ID_LEN)];
    char lock_name_json[C300X_JSON_QUOTED_LEN(C300X_MAX_LOCK_NAME_LEN)];

    if (strcmp(lock_id, config->lock_id) != 0) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"unknown_lock\"}\n");
        return;
    }
    snprintf(press, sizeof(press), "*8*19*%s##", config->lock_address);
    snprintf(release, sizeof(release), "*8*20*%s##", config->lock_address);
    if (!c300x_openwebnet_sequence(
        config,
        press,
        config->lock_release_delay_ms,
        release,
        error,
        sizeof(error)
    )) {
        send_device_error(client_fd, error);
        return;
    }
    json_string(config->lock_id, lock_id_json, sizeof(lock_id_json));
    json_string(config->lock_name, lock_name_json, sizeof(lock_name_json));
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"lock_id\":%s,\"name\":%s}\n",
        lock_id_json,
        lock_name_json
    );
    send_json(client_fd, 200, "OK", body);
}

static void handle_smartphone_get(int client_fd, const struct c300x_config *config)
{
    char reply[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    const char *mode;
    char body[2048];
    char reply_json[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN)];

    if (!c300x_openwebnet_send(config, "*#8**37##", reply, sizeof(reply), error, sizeof(error))) {
        send_device_error(client_fd, error);
        return;
    }
    json_string(reply, reply_json, sizeof(reply_json));
    mode = smartphone_mode_from_reply(reply);
    if (mode == NULL) {
        snprintf(body, sizeof(body), "{\"ok\":true,\"mode\":null,\"status\":\"unknown\",\"raw\":%s}\n", reply_json);
    } else {
        snprintf(body, sizeof(body), "{\"ok\":true,\"mode\":\"%s\",\"raw\":%s}\n", mode, reply_json);
    }
    send_json(client_fd, 200, "OK", body);
}

static void handle_smartphone_post(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    char mode[32];
    char command[64];
    char reply[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    const char *readback;
    char body[2048];
    char reply_json[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN)];
    int enabled;

    json_string_field(request->body, "mode", mode, sizeof(mode));
    if (mode[0] == '\0' && json_bool_field(request->body, "enabled", &enabled)) {
        snprintf(mode, sizeof(mode), "%s", enabled ? "enabled" : "blocked");
    }
    if (strcmp(mode, "enabled") == 0) {
        snprintf(command, sizeof(command), "*#8**#37*0##");
    } else if (strcmp(mode, "in-house-only") == 0) {
        snprintf(command, sizeof(command), "*#8**#37*1##");
    } else if (strcmp(mode, "blocked") == 0) {
        snprintf(command, sizeof(command), "*#8**#37*2##");
    } else {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_smartphone_forwarding_mode\"}\n");
        return;
    }
    if (!c300x_openwebnet_send(config, command, reply, sizeof(reply), error, sizeof(error))) {
        send_device_error(client_fd, error);
        return;
    }
    readback = smartphone_mode_from_reply(reply);
    json_string(reply, reply_json, sizeof(reply_json));
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"mode\":\"%s\",\"raw\":%s}\n",
        readback != NULL ? readback : mode,
        reply_json
    );
    send_json(client_fd, 200, "OK", body);
}

static void handle_ringer_get(int client_fd, const struct c300x_config *config)
{
    char reply[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    char body[2048];
    char reply_json[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN)];
    int muted;

    if (!c300x_openwebnet_send(config, "*#8**33##", reply, sizeof(reply), error, sizeof(error))) {
        send_device_error(client_fd, error);
        return;
    }
    json_string(reply, reply_json, sizeof(reply_json));
    if (ringer_muted_from_reply(reply, &muted)) {
        snprintf(body, sizeof(body), "{\"ok\":true,\"muted\":%s,\"raw\":%s}\n", muted ? "true" : "false", reply_json);
    } else {
        snprintf(body, sizeof(body), "{\"ok\":true,\"muted\":null,\"status\":\"unknown\",\"raw\":%s}\n", reply_json);
    }
    send_json(client_fd, 200, "OK", body);
}

static void handle_ringer_post(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    char reply[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    char body[2048];
    char reply_json[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN)];
    int muted;
    int enabled;
    int readback;
    const char *command;

    if (!json_bool_field(request->body, "muted", &muted)) {
        if (json_bool_field(request->body, "enabled", &enabled)) {
            muted = !enabled;
        } else {
            send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"ringer_muted_required\"}\n");
            return;
        }
    }
    command = muted ? "*#8**#33*0##" : "*#8**#33*1##";
    if (!c300x_openwebnet_send(config, command, reply, sizeof(reply), error, sizeof(error))) {
        send_device_error(client_fd, error);
        return;
    }
    if (!ringer_muted_from_reply(reply, &readback)) {
        readback = muted;
    }
    json_string(reply, reply_json, sizeof(reply_json));
    snprintf(body, sizeof(body), "{\"ok\":true,\"muted\":%s,\"raw\":%s}\n", readback ? "true" : "false", reply_json);
    send_json(client_fd, 200, "OK", body);
}

static void handle_answering_get(int client_fd, const struct c300x_config *config)
{
    char reply[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    char body[2048];
    char reply_json[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN)];
    int enabled = 0;
    int greeting = -1;

    if (!c300x_openwebnet_send(config, "*#8**40##", reply, sizeof(reply), error, sizeof(error))) {
        send_device_error(client_fd, error);
        return;
    }
    json_string(reply, reply_json, sizeof(reply_json));
    if (!answering_enabled_from_reply(reply, -1, &enabled, &greeting)) {
        snprintf(body, sizeof(body), "{\"ok\":true,\"enabled\":null,\"status\":\"unknown\",\"raw\":%s}\n", reply_json);
    } else {
        snprintf(
            body,
            sizeof(body),
            "{\"ok\":true,\"enabled\":%s,\"greeting_message_enabled\":%s,\"raw\":%s}\n",
            enabled ? "true" : "false",
            greeting < 0 ? "null" : (greeting ? "true" : "false"),
            reply_json
        );
    }
    send_json(client_fd, 200, "OK", body);
}

static void handle_answering_messages_get(int client_fd, struct agent_runtime *runtime)
{
    struct voicemail_snapshot *snapshot = calloc(1, sizeof(*snapshot));
    char *body = allocate_response_buffer(client_fd, C300X_LARGE_RESPONSE_SIZE);
    size_t used = 0;
    char newest_at[C300X_MAX_VOICEMAIL_DATE_LEN * 2];
    char reason[C300X_MAX_VOICEMAIL_REASON_LEN * 2];
    const char *newest_at_json = "null";
    const char *reason_json = "null";

    if (snapshot == NULL || body == NULL) {
        free(snapshot);
        free(body);
        return;
    }
    voicemail_refresh_watches(&runtime->voicemail);
    voicemail_read_snapshot(&runtime->voicemail, snapshot);
    if (snapshot->newest_at[0] != '\0') {
        json_escape_string(snapshot->newest_at, newest_at, sizeof(newest_at));
        newest_at_json = newest_at;
    }
    if (snapshot->reason[0] != '\0') {
        json_escape_string(snapshot->reason, reason, sizeof(reason));
        reason_json = reason;
    }
    if (!appendf(
        body,
        C300X_LARGE_RESPONSE_SIZE,
        &used,
        "{\"ok\":true,\"available\":%s,\"reason\":%s%s%s,\"total\":%d,\"unread\":%d,\"read\":%d,\"newest_at\":%s%s%s,\"messages\":[",
        snapshot->available ? "true" : "false",
        reason_json == reason ? "\"" : "",
        reason_json,
        reason_json == reason ? "\"" : "",
        snapshot->total,
        snapshot->unread,
        snapshot->read,
        newest_at_json == newest_at ? "\"" : "",
        newest_at_json,
        newest_at_json == newest_at ? "\"" : ""
    )) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        free(snapshot);
        free(body);
        return;
    }
    for (int index = 0; index < snapshot->message_count; index++) {
        const struct voicemail_message *message = &snapshot->messages[index];
        char message_id[C300X_MAX_VOICEMAIL_ID_LEN * 2];
        char date[C300X_MAX_VOICEMAIL_DATE_LEN * 2];
        char iso_time[80];
        char media_mime_type[96];
        char unix_time_json[32];
        char media_size_json[32];
        const char *read_json = "null";
        const char *date_json = "null";
        const char *iso_time_json = "null";
        const char *media_mime_type_json = "null";

        if (message->read == 0) {
            read_json = "false";
        } else if (message->read == 1) {
            read_json = "true";
        }
        json_escape_string(message->id, message_id, sizeof(message_id));
        if (message->date[0] != '\0') {
            json_escape_string(message->date, date, sizeof(date));
            date_json = date;
        }
        if (message->iso_time[0] != '\0') {
            json_escape_string(message->iso_time, iso_time, sizeof(iso_time));
            iso_time_json = iso_time;
        }
        if (message->video_mime_type[0] != '\0') {
            json_escape_string(message->video_mime_type, media_mime_type, sizeof(media_mime_type));
            media_mime_type_json = media_mime_type;
        }
        if (message->unix_time > 0) {
            snprintf(unix_time_json, sizeof(unix_time_json), "%lld", message->unix_time);
        } else {
            snprintf(unix_time_json, sizeof(unix_time_json), "null");
        }
        if (message->video_size > 0) {
            snprintf(media_size_json, sizeof(media_size_json), "%lld", message->video_size);
        } else {
            snprintf(media_size_json, sizeof(media_size_json), "null");
        }
        if (!appendf(
            body,
            C300X_LARGE_RESPONSE_SIZE,
            &used,
            "%s{\"id\":\"%s\",\"read\":%s,\"date\":%s%s%s,\"unix_time\":%s,\"iso_time\":%s%s%s,\"has_thumbnail\":%s,\"has_video\":%s,\"media_mime_type\":%s%s%s,\"media_size\":%s}",
            index == 0 ? "" : ",",
            message_id,
            read_json,
            date_json == date ? "\"" : "",
            date_json,
            date_json == date ? "\"" : "",
            unix_time_json,
            iso_time_json == iso_time ? "\"" : "",
            iso_time_json,
            iso_time_json == iso_time ? "\"" : "",
            message->has_thumbnail ? "true" : "false",
            message->has_video ? "true" : "false",
            media_mime_type_json == media_mime_type ? "\"" : "",
            media_mime_type_json,
            media_mime_type_json == media_mime_type ? "\"" : "",
            media_size_json
        )) {
            send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
            free(snapshot);
            free(body);
            return;
        }
    }
    if (!appendf(body, C300X_LARGE_RESPONSE_SIZE, &used, "]}\n")) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        free(snapshot);
        free(body);
        return;
    }
    send_json(client_fd, 200, "OK", body);
    free(snapshot);
    free(body);
}

static void handle_answering_message_video_get(
    int client_fd,
    const struct agent_runtime *runtime,
    const char *message_id
)
{
    char video_path[C300X_MAX_PATH_LEN];
    const char *content_type = "application/octet-stream";
    long long size = 0;

    if (!safe_voicemail_entry_name(message_id)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_message_id\"}\n");
        return;
    }
    if (!find_answering_message_video(
        &runtime->voicemail,
        message_id,
        video_path,
        sizeof(video_path),
        &content_type,
        &size
    )) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"video_message_not_found\"}\n");
        return;
    }
    (void)size;
    send_file_response(client_fd, video_path, content_type, "no-store");
}

static void handle_answering_message_delete(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    char message_id[C300X_MAX_VOICEMAIL_ID_LEN];
    char message_path[C300X_MAX_PATH_LEN];
    char message_id_json[256];
    char reply[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    char body[256];
    int message_number = 0;
    int is_symlink = 0;
    int path_present = 1;

    if (!config->answering_machine_messages_enabled || !runtime->voicemail.enabled) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"video_messages_disabled\"}\n");
        return;
    }
    json_string_field(request->body, "id", message_id, sizeof(message_id));
    if (!safe_voicemail_entry_name(message_id)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_message_id\"}\n");
        return;
    }
    if (snprintf(message_path, sizeof(message_path), "%s/%s", runtime->voicemail.root, message_id) >= (int)sizeof(message_path)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_message_id\"}\n");
        return;
    }
    if (!entry_number_from_prefixed_name(message_id, "message_", &message_number)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_message_id\"}\n");
        return;
    }
    if (!path_is_symlink(message_path, &is_symlink)) {
        if (errno == ENOENT) {
            path_present = 0;
        } else {
            send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"video_message_stat_failed\"}\n");
            return;
        }
    }
    if (path_present && (is_symlink || !path_is_directory(message_path))) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_message_entry\"}\n");
        return;
    }
    if (!send_answering_delete_command(
        config,
        message_number,
        C300X_ANSWERING_DIRECTORY_VIDEO_MESSAGE,
        reply,
        sizeof(reply),
        error,
        sizeof(error)
    )) {
        send_device_error(client_fd, error);
        return;
    }
    if (path_present && !wait_for_path_absent(message_path, 3000)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"video_message_delete_timeout\"}\n");
        return;
    }

    voicemail_refresh_watches(&runtime->voicemail);
    voicemail_event_dispatch_if_changed(config, runtime);
    record_agent_write(config, runtime, "memo_delete", "video_message");

    json_string(message_id, message_id_json, sizeof(message_id_json));
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"deleted\":true,\"id\":%s}\n",
        message_id_json
    );
    send_json(client_fd, 200, "OK", body);
}

static int append_memo_entries(
    char *body,
    size_t body_len,
    size_t *used,
    const struct voicemail_snapshot *snapshot,
    const char *kind,
    int *first
)
{
    for (int index = 0; index < snapshot->message_count; index++) {
        const struct voicemail_message *message = &snapshot->messages[index];
        char message_id[C300X_MAX_VOICEMAIL_ID_LEN * 2];
        char date[C300X_MAX_VOICEMAIL_DATE_LEN * 2];
        char iso_time[80];
        char text[C300X_MAX_MEMO_TEXT_JSON_LEN];
        char audio_mime_type[96];
        char unix_time_json[32];
        char audio_size_json[32];
        const char *read_json = "null";
        const char *date_json = "null";
        const char *iso_time_json = "null";
        const char *text_json = "null";
        const char *audio_mime_type_json = "null";

        if (message->read == 0) {
            read_json = "false";
        } else if (message->read == 1) {
            read_json = "true";
        }
        json_escape_string(message->id, message_id, sizeof(message_id));
        if (message->date[0] != '\0') {
            json_escape_string(message->date, date, sizeof(date));
            date_json = date;
        }
        if (message->iso_time[0] != '\0') {
            json_escape_string(message->iso_time, iso_time, sizeof(iso_time));
            iso_time_json = iso_time;
        }
        if (message->text[0] != '\0') {
            json_escape_string(message->text, text, sizeof(text));
            text_json = text;
        }
        if (message->audio_mime_type[0] != '\0') {
            json_escape_string(message->audio_mime_type, audio_mime_type, sizeof(audio_mime_type));
            audio_mime_type_json = audio_mime_type;
        }
        if (message->unix_time > 0) {
            snprintf(unix_time_json, sizeof(unix_time_json), "%lld", message->unix_time);
        } else {
            snprintf(unix_time_json, sizeof(unix_time_json), "null");
        }
        if (message->audio_size > 0) {
            snprintf(audio_size_json, sizeof(audio_size_json), "%lld", message->audio_size);
        } else {
            snprintf(audio_size_json, sizeof(audio_size_json), "null");
        }
        if (!appendf(
            body,
            body_len,
            used,
            "%s{\"id\":\"%s/%s\",\"kind\":\"%s\",\"read\":%s,\"date\":%s%s%s,\"unix_time\":%s,\"iso_time\":%s%s%s,\"has_text\":%s,\"has_audio\":%s,\"audio_mime_type\":%s%s%s,\"audio_size\":%s,\"text\":%s%s%s,\"text_truncated\":%s}",
            *first ? "" : ",",
            kind,
            message_id,
            kind,
            read_json,
            date_json == date ? "\"" : "",
            date_json,
            date_json == date ? "\"" : "",
            unix_time_json,
            iso_time_json == iso_time ? "\"" : "",
            iso_time_json,
            iso_time_json == iso_time ? "\"" : "",
            message->has_text ? "true" : "false",
            message->has_audio ? "true" : "false",
            audio_mime_type_json == audio_mime_type ? "\"" : "",
            audio_mime_type_json,
            audio_mime_type_json == audio_mime_type ? "\"" : "",
            audio_size_json,
            text_json == text ? "\"" : "",
            text_json,
            text_json == text ? "\"" : "",
            message->text_truncated ? "true" : "false"
        )) {
            return 0;
        }
        *first = 0;
    }
    return 1;
}

static void handle_memos_get(int client_fd, const struct agent_runtime *runtime)
{
    struct voicemail_snapshot *text = calloc(1, sizeof(*text));
    struct voicemail_snapshot *voice = calloc(1, sizeof(*voice));
    char *body = allocate_response_buffer(client_fd, C300X_LARGE_RESPONSE_SIZE);
    size_t used = 0;
    char newest_at_escaped[C300X_MAX_VOICEMAIL_DATE_LEN * 2];
    const char *newest_at_json = "null";
    const char *newest_at_value;
    int first = 1;

    if (text == NULL || voice == NULL || body == NULL) {
        free(text);
        free(voice);
        free(body);
        return;
    }
    message_collection_read_snapshot(&runtime->text_memos, "text", text);
    message_collection_read_snapshot(&runtime->voice_memos, "voice", voice);
    newest_at_value = newest_memo_time(text, voice);
    if (newest_at_value[0] != '\0') {
        json_escape_string(newest_at_value, newest_at_escaped, sizeof(newest_at_escaped));
        newest_at_json = newest_at_escaped;
    }
    if (!appendf(
        body,
        C300X_LARGE_RESPONSE_SIZE,
        &used,
        "{\"ok\":true,\"available\":%s,\"total\":%d,\"text_total\":%d,\"voice_total\":%d,\"unread\":%d,\"read\":%d,\"newest_at\":%s%s%s,\"memos\":[",
        (text->available || voice->available) ? "true" : "false",
        text->total + voice->total,
        text->total,
        voice->total,
        text->unread + voice->unread,
        text->read + voice->read,
        newest_at_json == newest_at_escaped ? "\"" : "",
        newest_at_json,
        newest_at_json == newest_at_escaped ? "\"" : ""
    )) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        free(text);
        free(voice);
        free(body);
        return;
    }
    if (!append_memo_entries(body, C300X_LARGE_RESPONSE_SIZE, &used, text, "text", &first)
        || !append_memo_entries(body, C300X_LARGE_RESPONSE_SIZE, &used, voice, "voice", &first)
        || !appendf(body, C300X_LARGE_RESPONSE_SIZE, &used, "]}\n")) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"response_too_large\"}\n");
        free(text);
        free(voice);
        free(body);
        return;
    }
    send_json(client_fd, 200, "OK", body);
    free(text);
    free(voice);
    free(body);
}

static void handle_memo_audio_get(
    int client_fd,
    const struct agent_runtime *runtime,
    const char *memo_entry_name
)
{
    char audio_path[C300X_MAX_PATH_LEN];
    const char *content_type = "application/octet-stream";
    long long size = 0;

    if (!safe_voicemail_entry_name(memo_entry_name)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_memo_id\"}\n");
        return;
    }
    if (!find_memo_audio(
        &runtime->voice_memos,
        memo_entry_name,
        audio_path,
        sizeof(audio_path),
        &content_type,
        &size
    )) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"voice_memo_audio_not_found\"}\n");
        return;
    }
    (void)size;
    send_file_response(client_fd, audio_path, content_type, "no-store");
}

static void handle_memos_delete(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    struct voicemail_runtime *collection;
    char memo_id[128];
    char kind[16];
    char entry_name[C300X_MAX_VOICEMAIL_ID_LEN];
    char memo_path[C300X_MAX_PATH_LEN];
    char reply[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    char body[256];
    char memo_id_json[256];
    char kind_json[48];
    int memo_number = 0;
    int memo_directory = 0;
    int is_symlink = 0;
    int path_present = 1;

    if (!config->memos_enabled) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"memos_disabled\"}\n");
        return;
    }
    json_string_field(request->body, "id", memo_id, sizeof(memo_id));
    if (!parse_memo_id(memo_id, kind, sizeof(kind), entry_name, sizeof(entry_name))) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_memo_id\"}\n");
        return;
    }
    collection = strcmp(kind, "text") == 0 ? &runtime->text_memos : &runtime->voice_memos;
    if (!collection->enabled || collection->root[0] == '\0') {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"memos_disabled\"}\n");
        return;
    }
    if (snprintf(memo_path, sizeof(memo_path), "%s/%s", collection->root, entry_name) >= (int)sizeof(memo_path)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_memo_id\"}\n");
        return;
    }
    if (!entry_number_from_prefixed_name(entry_name, "memo_", &memo_number)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_memo_id\"}\n");
        return;
    }
    memo_directory = strcmp(kind, "text") == 0
        ? C300X_ANSWERING_DIRECTORY_TEXT_MEMO
        : C300X_ANSWERING_DIRECTORY_VOICE_MEMO;
    if (!path_is_symlink(memo_path, &is_symlink)) {
        if (errno == ENOENT) {
            path_present = 0;
        } else {
            send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"memo_stat_failed\"}\n");
            return;
        }
    }
    if (path_present && (is_symlink || !path_is_directory(memo_path))) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_memo_entry\"}\n");
        return;
    }
    if (!send_answering_delete_command(
        config,
        memo_number,
        memo_directory,
        reply,
        sizeof(reply),
        error,
        sizeof(error)
    )) {
        send_device_error(client_fd, error);
        return;
    }
    if (path_present && !wait_for_path_absent(memo_path, 3000)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"memo_delete_timeout\"}\n");
        return;
    }

    voicemail_refresh_watches(&runtime->text_memos);
    voicemail_refresh_watches(&runtime->voice_memos);
    memos_event_dispatch_if_changed(config, runtime);
    record_agent_write(config, runtime, "memo_delete", kind);

    json_string(memo_id, memo_id_json, sizeof(memo_id_json));
    json_string(kind, kind_json, sizeof(kind_json));
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"deleted\":true,\"id\":%s,\"kind\":%s}\n",
        memo_id_json,
        kind_json
    );
    send_json(client_fd, 200, "OK", body);
}

static void handle_answering_post(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    char reply[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    char body[2048];
    char reply_json[C300X_JSON_QUOTED_LEN(C300X_MAX_FRAME_LEN)];
    int enabled;
    int readback = 0;
    int greeting = -1;

    if (!json_bool_field(request->body, "enabled", &enabled)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"answering_machine_enabled_required\"}\n");
        return;
    }
    if (!c300x_openwebnet_send(
        config,
        enabled ? "*8*91##" : "*8*92##",
        reply,
        sizeof(reply),
        error,
        sizeof(error)
    )) {
        send_device_error(client_fd, error);
        return;
    }
    if (!answering_enabled_from_reply(reply, enabled, &readback, &greeting)) {
        readback = enabled;
    }
    json_string(reply, reply_json, sizeof(reply_json));
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"enabled\":%s,\"greeting_message_enabled\":%s,\"raw\":%s}\n",
        readback ? "true" : "false",
        greeting < 0 ? "null" : (greeting ? "true" : "false"),
        reply_json
    );
    send_json(client_fd, 200, "OK", body);
}

static int maintenance_authorized(const struct c300x_config *config, const struct request *request)
{
    char supplied[C300X_MAX_TOKEN_LEN];

    if (!config->maintenance_enabled) {
        return 0;
    }
    if (config->api_no_auth && config->maintenance_no_auth_allowed) {
        return 1;
    }
    if (config->maintenance_admin_token[0] == '\0') {
        return 0;
    }
    if (!header_value(request, "x-bticino-c300x-maintenance-token", supplied, sizeof(supplied))) {
        return 0;
    }
    return constant_time_equal(
        supplied,
        strlen(supplied),
        config->maintenance_admin_token
    );
}

static int maintenance_auth_available(const struct c300x_config *config)
{
    return config->maintenance_enabled
        && (
            config->maintenance_admin_token[0] != '\0'
            || (config->api_no_auth && config->maintenance_no_auth_allowed)
        );
}

static int config_admin_authorized(const struct c300x_config *config, const struct request *request)
{
    return has_valid_bearer(request, config->api_token)
        || maintenance_authorized(config, request);
}

static int auth_config_read_authorized(const struct c300x_config *config, const struct request *request)
{
    return config->api_no_auth || config_admin_authorized(config, request);
}

static int confirm_matches(const struct request *request, const char *expected)
{
    char confirm[32];
    json_string_field(request->body, "confirm", confirm, sizeof(confirm));
    return strcmp(confirm, expected) == 0;
}

static int run_detached_command(const char *program, const char *argument, int delay_ms)
{
    pid_t pid = fork();
    if (pid < 0) {
        return 0;
    }
    if (pid == 0) {
        if (delay_ms > 0) {
            sleep_ms(delay_ms);
        }
        if (argument != NULL) {
            execl(program, program, argument, (char *)NULL);
        } else {
            execl(program, program, (char *)NULL);
        }
        _exit(127);
    }
    if (delay_ms <= 0) {
        int status = 0;
        if (waitpid(pid, &status, 0) < 0) {
            return 0;
        }
        return WIFEXITED(status) && WEXITSTATUS(status) == 0;
    }
    return 1;
}

static int run_command_capture(
    const char *program,
    const char *argument,
    char *out,
    size_t out_len,
    int timeout_ms,
    int *exit_code
)
{
    const int interval_ms = 50;
    int pipe_fd[2];
    int status = 0;
    int waited_ms = 0;
    int child_done = 0;
    size_t used = 0;
    pid_t pid;

    if (out_len > 0) {
        out[0] = '\0';
    }
    if (exit_code != NULL) {
        *exit_code = -1;
    }
    if (program == NULL || program[0] == '\0' || access(program, X_OK) != 0) {
        return 0;
    }
    if (pipe(pipe_fd) != 0) {
        return 0;
    }
    pid = fork();
    if (pid < 0) {
        close(pipe_fd[0]);
        close(pipe_fd[1]);
        return 0;
    }
    if (pid == 0) {
        int null_fd;
        close(pipe_fd[0]);
        (void)dup2(pipe_fd[1], STDOUT_FILENO);
        null_fd = open("/dev/null", O_WRONLY);
        if (null_fd >= 0) {
            (void)dup2(null_fd, STDERR_FILENO);
            close(null_fd);
        }
        close(pipe_fd[1]);
        execl(program, program, argument, (char *)NULL);
        _exit(127);
    }
    close(pipe_fd[1]);
    set_fd_nonblocking(pipe_fd[0]);

    while (!child_done) {
        for (;;) {
            char discard[256];
            size_t capacity = out_len > used + 1 ? out_len - used - 1 : 0;
            ssize_t read_size = read(
                pipe_fd[0],
                capacity > 0 ? out + used : discard,
                capacity > 0 ? capacity : sizeof(discard)
            );
            if (read_size > 0) {
                if (capacity > 0) {
                    used += (size_t)read_size;
                }
                continue;
            }
            if (read_size < 0 && errno == EINTR) {
                continue;
            }
            break;
        }
        if (waitpid(pid, &status, WNOHANG) == pid) {
            child_done = 1;
            break;
        }
        if (waited_ms >= timeout_ms) {
            (void)kill(pid, SIGKILL);
            (void)waitpid(pid, &status, 0);
            close(pipe_fd[0]);
            if (out_len > 0) {
                out[used < out_len ? used : out_len - 1] = '\0';
            }
            return 0;
        }
        sleep_ms(interval_ms);
        waited_ms += interval_ms;
    }
    for (;;) {
        char discard[256];
        size_t capacity = out_len > used + 1 ? out_len - used - 1 : 0;
        ssize_t read_size = read(
            pipe_fd[0],
            capacity > 0 ? out + used : discard,
            capacity > 0 ? capacity : sizeof(discard)
        );
        if (read_size > 0) {
            if (capacity > 0) {
                used += (size_t)read_size;
            }
            continue;
        }
        if (read_size < 0 && errno == EINTR) {
            continue;
        }
        break;
    }
    close(pipe_fd[0]);
    if (out_len > 0) {
        out[used < out_len ? used : out_len - 1] = '\0';
    }
    if (exit_code != NULL && WIFEXITED(status)) {
        *exit_code = WEXITSTATUS(status);
    }
    return WIFEXITED(status) && WEXITSTATUS(status) == 0;
}

static int ssh_service_running(void)
{
    int status = system("pidof dropbear >/dev/null 2>&1");
    return status != -1 && WIFEXITED(status) && WEXITSTATUS(status) == 0;
}

static void send_ssh_status(int client_fd)
{
    char body[96];
    int running = ssh_service_running();
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"enabled\":%s,\"running\":%s}\n",
        running ? "true" : "false",
        running ? "true" : "false"
    );
    send_json(client_fd, 200, "OK", body);
}

static int maintenance_ssh_supported(const struct c300x_config *config)
{
    return (
        maintenance_auth_available(config)
        && config->maintenance_ssh_start_enabled
    );
}

static int maintenance_qml_patch_supported(const struct c300x_config *config)
{
    return (
        maintenance_auth_available(config)
        && config->maintenance_qml_patch_enabled
    );
}

static int maintenance_agent_remove_supported(const struct c300x_config *config)
{
    return (
        maintenance_auth_available(config)
        && config->maintenance_agent_remove_enabled
    );
}

static int maintenance_gui_reload_supported(const struct c300x_config *config)
{
    return (
        maintenance_auth_available(config)
        && config->maintenance_gui_reload_enabled
    );
}

static int maintenance_firewall_supported(const struct c300x_config *config)
{
    return (
        maintenance_auth_available(config)
        && config->maintenance_firewall_enabled
    );
}

static int maintenance_ipv6_firewall_supported(const struct c300x_config *config)
{
    return (
        maintenance_auth_available(config)
        && config->maintenance_ipv6_firewall_enabled
    );
}

static int firewall_path_requires_remount(const char *path)
{
    return path != NULL && strncmp(path, "/etc/", 5) == 0;
}

static void firewall_remount_rw_if_needed(const char *path)
{
    if (firewall_path_requires_remount(path)) {
        int status = system("mount -o remount,rw / >/dev/null 2>&1");
        (void)status;
    }
}

static void firewall_remount_ro_if_needed(const char *path)
{
    if (firewall_path_requires_remount(path)) {
        int status = system("mount -o remount,ro / >/dev/null 2>&1");
        (void)status;
    }
}

static int firewall_read_file(
    const char *path,
    char *buffer,
    size_t buffer_len,
    int *exists
)
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

static int firewall_write_file(
    const char *path,
    const char *content,
    mode_t mode
)
{
    char temporary_path[C300X_MAX_PATH_LEN + 8];
    FILE *file;

    if (!mkdir_parent(path, 0755)) {
        return 0;
    }
    if (snprintf(temporary_path, sizeof(temporary_path), "%s.tmp", path) >= (int)sizeof(temporary_path)) {
        return 0;
    }
    file = fopen(temporary_path, "w");
    if (file == NULL) {
        return 0;
    }
    if (fputs(content, file) == EOF) {
        (void)fclose(file);
        (void)unlink(temporary_path);
        return 0;
    }
    if (fclose(file) != 0) {
        (void)unlink(temporary_path);
        return 0;
    }
    (void)chmod(temporary_path, mode);
    if (rename(temporary_path, path) != 0) {
        (void)unlink(temporary_path);
        return 0;
    }
    (void)chmod(path, mode);
    return 1;
}

static int firewall_backup_available(const char *backup_path)
{
    return path_exists(backup_path);
}

static int firewall_block_bounds_for(
    const char *content,
    const char *begin_marker,
    const char *end_marker,
    const char **block_start,
    const char **block_end
)
{
    const char *begin = strstr(content, begin_marker);
    const char *end;
    const char *line_end;

    if (block_start != NULL) {
        *block_start = NULL;
    }
    if (block_end != NULL) {
        *block_end = NULL;
    }
    if (begin == NULL) {
        return 0;
    }
    end = strstr(begin, end_marker);
    if (end == NULL) {
        return -1;
    }
    while (begin > content && begin[-1] != '\n') {
        begin--;
    }
    line_end = strchr(end, '\n');
    if (line_end == NULL) {
        line_end = end + strlen(end);
    } else {
        line_end++;
    }
    if (block_start != NULL) {
        *block_start = begin;
    }
    if (block_end != NULL) {
        *block_end = line_end;
    }
    return 1;
}

static int firewall_block_bounds(
    const char *content,
    const char **block_start,
    const char **block_end
)
{
    return firewall_block_bounds_for(
        content,
        C300X_FIREWALL_BEGIN,
        C300X_FIREWALL_END,
        block_start,
        block_end
    );
}

static int firewall_remove_block_for(
    const char *content,
    const char *begin_marker,
    const char *end_marker,
    char *out,
    size_t out_len
)
{
    const char *start;
    const char *end;
    size_t prefix_len;

    if (firewall_block_bounds_for(content, begin_marker, end_marker, &start, &end) < 0) {
        return 0;
    }
    if (start == NULL || end == NULL) {
        return snprintf(out, out_len, "%s", content) < (int)out_len;
    }
    prefix_len = (size_t)(start - content);
    if (prefix_len + strlen(end) + 1 > out_len) {
        return 0;
    }
    memcpy(out, content, prefix_len);
    out[prefix_len] = '\0';
    snprintf(out + prefix_len, out_len - prefix_len, "%s", end);
    while (out[0] != '\0' && strlen(out) > 1 && out[strlen(out) - 1] == '\n' && out[strlen(out) - 2] == '\n') {
        out[strlen(out) - 1] = '\0';
    }
    return 1;
}

static int firewall_remove_block(
    const char *content,
    char *out,
    size_t out_len
)
{
    return firewall_remove_block_for(
        content,
        C300X_FIREWALL_BEGIN,
        C300X_FIREWALL_END,
        out,
        out_len
    );
}

static int firewall_remove_all_managed_blocks(
    const char *content,
    char *out,
    size_t out_len
)
{
    char *without_ipv4 = calloc(1, C300X_FIREWALL_BUFFER_SIZE);
    int ok;

    if (without_ipv4 == NULL) {
        return 0;
    }
    ok = firewall_remove_block_for(
        content,
        C300X_FIREWALL_BEGIN,
        C300X_FIREWALL_END,
        without_ipv4,
        C300X_FIREWALL_BUFFER_SIZE
    );
    if (!ok) {
        free(without_ipv4);
        return 0;
    }
    ok = firewall_remove_block_for(
        without_ipv4,
        C300X_IPV6_FIREWALL_BEGIN,
        C300X_IPV6_FIREWALL_END,
        out,
        out_len
    );
    free(without_ipv4);
    return ok;
}

static int firewall_build_managed_content(
    const struct c300x_config *config,
    const char *base,
    char *out,
    size_t out_len
)
{
    const char *separator = "";

    if (base[0] != '\0' && base[strlen(base) - 1] != '\n') {
        separator = "\n\n";
    } else if (base[0] != '\0') {
        separator = "\n";
    }
    return snprintf(
        out,
        out_len,
        "%s%s"
        "%s\n"
        "# Managed by c300x-native-agent. Opens only the configured API port.\n"
        "if command -v iptables >/dev/null 2>&1; then\n"
        "    if ! iptables -C INPUT -p tcp --dport %u -j ACCEPT 2>/dev/null; then\n"
        "        iptables -A INPUT -p tcp --dport %u -j ACCEPT\n"
        "    fi\n"
        "fi\n"
        "%s\n",
        base,
        separator,
        C300X_FIREWALL_BEGIN,
        config->api_port,
        config->api_port,
        C300X_FIREWALL_END
    ) < (int)out_len;
}

static int firewall_build_ipv6_managed_content(
    const struct c300x_config *config,
    const char *base,
    char *out,
    size_t out_len
)
{
    const char *separator = "";

    if (base[0] != '\0' && base[strlen(base) - 1] != '\n') {
        separator = "\n\n";
    } else if (base[0] != '\0') {
        separator = "\n";
    }
    return snprintf(
        out,
        out_len,
        "%s%s"
        "%s\n"
        "# Managed by c300x-native-agent. Opens IPv6 ICMP and the configured API port.\n"
        "if command -v ip6tables >/dev/null 2>&1; then\n"
        "    if ! ip6tables -C INPUT -p ipv6-icmp -j ACCEPT 2>/dev/null; then\n"
        "        ip6tables -I INPUT 1 -p ipv6-icmp -j ACCEPT\n"
        "    fi\n"
        "    if ! ip6tables -C INPUT -p tcp --dport %u -j ACCEPT 2>/dev/null; then\n"
        "        ip6tables -I INPUT 1 -p tcp --dport %u -j ACCEPT\n"
        "    fi\n"
        "    if ! ip6tables -C INPUT -p tcp --sport %u -j ACCEPT 2>/dev/null; then\n"
        "        ip6tables -I INPUT 1 -p tcp --sport %u -j ACCEPT\n"
        "    fi\n"
        "fi\n"
        "%s\n",
        base,
        separator,
        C300X_IPV6_FIREWALL_BEGIN,
        config->api_port,
        config->api_port,
        config->api_port,
        config->api_port,
        C300X_IPV6_FIREWALL_END
    ) < (int)out_len;
}

static const char *firewall_state_for_content_for(
    const char *content,
    int exists,
    const char *begin_marker,
    const char *end_marker
)
{
    int block_state;

    if (!exists) {
        return "missing";
    }
    block_state = firewall_block_bounds_for(content, begin_marker, end_marker, NULL, NULL);
    if (block_state > 0) {
        return "patched";
    }
    if (block_state < 0 || strstr(content, end_marker) != NULL) {
        return "partial";
    }
    return "original";
}

static const char *firewall_state_for_content(const char *content, int exists)
{
    return firewall_state_for_content_for(
        content,
        exists,
        C300X_FIREWALL_BEGIN,
        C300X_FIREWALL_END
    );
}

static void send_firewall_status_body(
    int client_fd,
    const struct c300x_config *config,
    const char *family,
    const char *state,
    int exists,
    int changed_files
)
{
    const char *path = strcmp(family, "ipv6") == 0
        ? config->maintenance_ipv6_firewall_path
        : config->maintenance_firewall_path;
    const char *backup_path = strcmp(family, "ipv6") == 0
        ? config->maintenance_ipv6_firewall_backup_path
        : config->maintenance_firewall_backup_path;
    char path_json[C300X_JSON_QUOTED_LEN(C300X_MAX_PATH_LEN)];
    char backup_path_json[C300X_JSON_QUOTED_LEN(C300X_MAX_PATH_LEN)];
    char family_json[C300X_JSON_QUOTED_LEN(8)];
    char changed_json[32] = "";
    char body[1024];

    json_string(family, family_json, sizeof(family_json));
    json_string(path, path_json, sizeof(path_json));
    json_string(
        backup_path,
        backup_path_json,
        sizeof(backup_path_json)
    );
    if (changed_files >= 0) {
        snprintf(changed_json, sizeof(changed_json), ",\"changed_files\":%d", changed_files);
    }
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"available\":true,\"state\":\"%s\",\"patched\":%s,"
        "\"family\":%s,\"exists\":%s,\"backup_available\":%s,\"api_port\":%u,"
        "\"path\":%s,\"backup_path\":%s%s}\n",
        state,
        strcmp(state, "patched") == 0 ? "true" : strcmp(state, "partial") == 0 ? "null" : "false",
        family_json,
        exists ? "true" : "false",
        firewall_backup_available(backup_path) ? "true" : "false",
        config->api_port,
        path_json,
        backup_path_json,
        changed_json
    );
    send_json(client_fd, 200, "OK", body);
}

static void handle_firewall_status(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    char *current = allocate_response_buffer(client_fd, C300X_FIREWALL_BUFFER_SIZE);
    int exists = 0;

    if (current == NULL) {
        return;
    }
    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        free(current);
        return;
    }
    if (!maintenance_firewall_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        free(current);
        return;
    }
    if (!firewall_read_file(config->maintenance_firewall_path, current, C300X_FIREWALL_BUFFER_SIZE, &exists)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"firewall_status_failed\"}\n");
        free(current);
        return;
    }
    send_firewall_status_body(
        client_fd,
        config,
        "ipv4",
        firewall_state_for_content(current, exists),
        exists,
        -1
    );
    free(current);
}

static int firewall_backup_original_if_needed(
    const char *backup_path,
    const char *backup_content,
    int *backup_written
)
{
    if (backup_written != NULL) {
        *backup_written = 0;
    }
    if (firewall_backup_available(backup_path)) {
        return 1;
    }
    if (!firewall_write_file(backup_path, backup_content, 0600)) {
        return 0;
    }
    if (backup_written != NULL) {
        *backup_written = 1;
    }
    return 1;
}

static int firewall_apply(
    const struct c300x_config *config,
    int *exists,
    int *changed_files,
    char *state,
    size_t state_len
)
{
    struct firewall_workspace *workspace = calloc(1, sizeof(*workspace));
    int current_exists = 0;
    int backup_written = 0;
    int target_written = 0;

    if (workspace == NULL) {
        return 0;
    }
    if (!firewall_read_file(config->maintenance_firewall_path, workspace->current, sizeof(workspace->current), &current_exists)) {
        free(workspace);
        return 0;
    }
    if (!current_exists) {
        snprintf(state, state_len, "%s", "missing");
        free(workspace);
        return 0;
    }
    if (firewall_block_bounds(workspace->current, NULL, NULL) < 0) {
        snprintf(state, state_len, "%s", "partial");
        free(workspace);
        return 0;
    }
    if (!firewall_remove_block(workspace->current, workspace->base, sizeof(workspace->base))) {
        free(workspace);
        return 0;
    }
    if (!firewall_remove_all_managed_blocks(workspace->current, workspace->original_backup, sizeof(workspace->original_backup))) {
        free(workspace);
        return 0;
    }
    if (!firewall_build_managed_content(config, workspace->base, workspace->desired, sizeof(workspace->desired))) {
        free(workspace);
        return 0;
    }
    if (strcmp(workspace->current, workspace->desired) == 0 && firewall_backup_available(config->maintenance_firewall_backup_path)) {
        if (exists != NULL) {
            *exists = current_exists;
        }
        if (changed_files != NULL) {
            *changed_files = 0;
        }
        snprintf(state, state_len, "%s", "patched");
        free(workspace);
        return 1;
    }
    firewall_remount_rw_if_needed(config->maintenance_firewall_path);
    if (current_exists && !firewall_backup_original_if_needed(config->maintenance_firewall_backup_path, workspace->original_backup, &backup_written)) {
        firewall_remount_ro_if_needed(config->maintenance_firewall_path);
        free(workspace);
        return 0;
    }
    if (strcmp(workspace->current, workspace->desired) != 0) {
        if (!firewall_write_file(config->maintenance_firewall_path, workspace->desired, 0755)) {
            firewall_remount_ro_if_needed(config->maintenance_firewall_path);
            free(workspace);
            return 0;
        }
        target_written = 1;
    }
    firewall_remount_ro_if_needed(config->maintenance_firewall_path);
    if (exists != NULL) {
        *exists = 1;
    }
    if (changed_files != NULL) {
        *changed_files = backup_written + target_written;
    }
    snprintf(state, state_len, "%s", "patched");
    free(workspace);
    return 1;
}

static int firewall_restore(
    const struct c300x_config *config,
    int *exists,
    int *changed_files,
    char *state,
    size_t state_len
)
{
    struct firewall_workspace *workspace = calloc(1, sizeof(*workspace));
    int current_exists = 0;
    int target_written = 0;

    if (workspace == NULL) {
        return 0;
    }
    if (!firewall_read_file(config->maintenance_firewall_path, workspace->current, sizeof(workspace->current), &current_exists)) {
        free(workspace);
        return 0;
    }
    if (firewall_block_bounds(workspace->current, NULL, NULL) < 0) {
        snprintf(state, state_len, "%s", "partial");
        free(workspace);
        return 0;
    }
    if (!firewall_remove_block(workspace->current, workspace->desired, sizeof(workspace->desired))) {
        free(workspace);
        return 0;
    }
    if (workspace->desired[0] == '\0' && firewall_backup_available(config->maintenance_firewall_backup_path)) {
        int backup_exists = 0;
        if (!firewall_read_file(
            config->maintenance_firewall_backup_path,
            workspace->desired,
            sizeof(workspace->desired),
            &backup_exists
        ) || !backup_exists) {
            free(workspace);
            return 0;
        }
    }
    if (strcmp(workspace->current, workspace->desired) == 0) {
        if (exists != NULL) {
            *exists = current_exists;
        }
        if (changed_files != NULL) {
            *changed_files = 0;
        }
        snprintf(state, state_len, "%s", firewall_state_for_content(workspace->current, current_exists));
        free(workspace);
        return 1;
    }
    firewall_remount_rw_if_needed(config->maintenance_firewall_path);
    if (workspace->desired[0] == '\0' && !firewall_backup_available(config->maintenance_firewall_backup_path)) {
        if (unlink(config->maintenance_firewall_path) != 0 && errno != ENOENT) {
            firewall_remount_ro_if_needed(config->maintenance_firewall_path);
            free(workspace);
            return 0;
        }
    } else if (!firewall_write_file(config->maintenance_firewall_path, workspace->desired, 0755)) {
        firewall_remount_ro_if_needed(config->maintenance_firewall_path);
        free(workspace);
        return 0;
    }
    target_written = 1;
    firewall_remount_ro_if_needed(config->maintenance_firewall_path);
    if (exists != NULL) {
        *exists = workspace->desired[0] != '\0' || firewall_backup_available(config->maintenance_firewall_backup_path);
    }
    if (changed_files != NULL) {
        *changed_files = target_written;
    }
    snprintf(state, state_len, "%s", workspace->desired[0] == '\0' ? "missing" : "original");
    free(workspace);
    return 1;
}

static const char *ipv6_firewall_state_for_content(const char *content, int exists)
{
    return firewall_state_for_content_for(
        content,
        exists,
        C300X_IPV6_FIREWALL_BEGIN,
        C300X_IPV6_FIREWALL_END
    );
}

static void handle_ipv6_firewall_status(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    char *current = allocate_response_buffer(client_fd, C300X_FIREWALL_BUFFER_SIZE);
    int exists = 0;

    if (current == NULL) {
        return;
    }
    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        free(current);
        return;
    }
    if (!maintenance_ipv6_firewall_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        free(current);
        return;
    }
    if (!firewall_read_file(config->maintenance_ipv6_firewall_path, current, C300X_FIREWALL_BUFFER_SIZE, &exists)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"firewall_status_failed\"}\n");
        free(current);
        return;
    }
    send_firewall_status_body(
        client_fd,
        config,
        "ipv6",
        ipv6_firewall_state_for_content(current, exists),
        exists,
        -1
    );
    free(current);
}

static int ipv6_firewall_apply(
    const struct c300x_config *config,
    int *exists,
    int *changed_files,
    char *state,
    size_t state_len
)
{
    struct firewall_workspace *workspace = calloc(1, sizeof(*workspace));
    int current_exists = 0;
    int backup_written = 0;
    int target_written = 0;

    if (workspace == NULL) {
        return 0;
    }
    if (!firewall_read_file(config->maintenance_ipv6_firewall_path, workspace->current, sizeof(workspace->current), &current_exists)) {
        free(workspace);
        return 0;
    }
    if (!current_exists) {
        snprintf(state, state_len, "%s", "missing");
        free(workspace);
        return 0;
    }
    if (firewall_block_bounds_for(workspace->current, C300X_IPV6_FIREWALL_BEGIN, C300X_IPV6_FIREWALL_END, NULL, NULL) < 0) {
        snprintf(state, state_len, "%s", "partial");
        free(workspace);
        return 0;
    }
    if (!firewall_remove_block_for(
        workspace->current,
        C300X_IPV6_FIREWALL_BEGIN,
        C300X_IPV6_FIREWALL_END,
        workspace->base,
        sizeof(workspace->base)
    )) {
        free(workspace);
        return 0;
    }
    if (!firewall_remove_all_managed_blocks(workspace->current, workspace->original_backup, sizeof(workspace->original_backup))) {
        free(workspace);
        return 0;
    }
    if (!firewall_build_ipv6_managed_content(config, workspace->base, workspace->desired, sizeof(workspace->desired))) {
        free(workspace);
        return 0;
    }
    if (strcmp(workspace->current, workspace->desired) == 0 && firewall_backup_available(config->maintenance_ipv6_firewall_backup_path)) {
        if (exists != NULL) {
            *exists = current_exists;
        }
        if (changed_files != NULL) {
            *changed_files = 0;
        }
        snprintf(state, state_len, "%s", "patched");
        free(workspace);
        return 1;
    }
    firewall_remount_rw_if_needed(config->maintenance_ipv6_firewall_path);
    if (current_exists && !firewall_backup_original_if_needed(config->maintenance_ipv6_firewall_backup_path, workspace->original_backup, &backup_written)) {
        firewall_remount_ro_if_needed(config->maintenance_ipv6_firewall_path);
        free(workspace);
        return 0;
    }
    if (strcmp(workspace->current, workspace->desired) != 0) {
        if (!firewall_write_file(config->maintenance_ipv6_firewall_path, workspace->desired, 0755)) {
            firewall_remount_ro_if_needed(config->maintenance_ipv6_firewall_path);
            free(workspace);
            return 0;
        }
        target_written = 1;
    }
    firewall_remount_ro_if_needed(config->maintenance_ipv6_firewall_path);
    if (exists != NULL) {
        *exists = 1;
    }
    if (changed_files != NULL) {
        *changed_files = backup_written + target_written;
    }
    snprintf(state, state_len, "%s", "patched");
    free(workspace);
    return 1;
}

static int ipv6_firewall_restore(
    const struct c300x_config *config,
    int *exists,
    int *changed_files,
    char *state,
    size_t state_len
)
{
    struct firewall_workspace *workspace = calloc(1, sizeof(*workspace));
    int current_exists = 0;
    int target_written = 0;

    if (workspace == NULL) {
        return 0;
    }
    if (!firewall_read_file(config->maintenance_ipv6_firewall_path, workspace->current, sizeof(workspace->current), &current_exists)) {
        free(workspace);
        return 0;
    }
    if (firewall_block_bounds_for(workspace->current, C300X_IPV6_FIREWALL_BEGIN, C300X_IPV6_FIREWALL_END, NULL, NULL) < 0) {
        snprintf(state, state_len, "%s", "partial");
        free(workspace);
        return 0;
    }
    if (!firewall_remove_block_for(
        workspace->current,
        C300X_IPV6_FIREWALL_BEGIN,
        C300X_IPV6_FIREWALL_END,
        workspace->desired,
        sizeof(workspace->desired)
    )) {
        free(workspace);
        return 0;
    }
    if (workspace->desired[0] == '\0' && firewall_backup_available(config->maintenance_ipv6_firewall_backup_path)) {
        int backup_exists = 0;
        if (!firewall_read_file(
            config->maintenance_ipv6_firewall_backup_path,
            workspace->desired,
            sizeof(workspace->desired),
            &backup_exists
        ) || !backup_exists) {
            free(workspace);
            return 0;
        }
    }
    if (strcmp(workspace->current, workspace->desired) == 0) {
        if (exists != NULL) {
            *exists = current_exists;
        }
        if (changed_files != NULL) {
            *changed_files = 0;
        }
        snprintf(state, state_len, "%s", ipv6_firewall_state_for_content(workspace->current, current_exists));
        free(workspace);
        return 1;
    }
    firewall_remount_rw_if_needed(config->maintenance_ipv6_firewall_path);
    if (workspace->desired[0] == '\0' && !firewall_backup_available(config->maintenance_ipv6_firewall_backup_path)) {
        if (unlink(config->maintenance_ipv6_firewall_path) != 0 && errno != ENOENT) {
            firewall_remount_ro_if_needed(config->maintenance_ipv6_firewall_path);
            free(workspace);
            return 0;
        }
    } else if (!firewall_write_file(config->maintenance_ipv6_firewall_path, workspace->desired, 0755)) {
        firewall_remount_ro_if_needed(config->maintenance_ipv6_firewall_path);
        free(workspace);
        return 0;
    }
    target_written = 1;
    firewall_remount_ro_if_needed(config->maintenance_ipv6_firewall_path);
    if (exists != NULL) {
        *exists = workspace->desired[0] != '\0' || firewall_backup_available(config->maintenance_ipv6_firewall_backup_path);
    }
    if (changed_files != NULL) {
        *changed_files = target_written;
    }
    snprintf(state, state_len, "%s", workspace->desired[0] == '\0' ? "missing" : "original");
    free(workspace);
    return 1;
}

static void handle_ipv6_firewall_action(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request,
    const char *action,
    const char *confirmation
)
{
    char state[32] = "unknown";
    int exists = 0;
    int changed_files = 0;
    int ok;

    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!maintenance_ipv6_firewall_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return;
    }
    if (!confirm_matches(request, confirmation)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return;
    }
    ok = strcmp(action, "apply") == 0
        ? ipv6_firewall_apply(config, &exists, &changed_files, state, sizeof(state))
        : ipv6_firewall_restore(config, &exists, &changed_files, state, sizeof(state));
    if (!ok) {
        if (strcmp(state, "partial") == 0) {
            send_json(client_fd, 409, "Conflict", "{\"ok\":false,\"error\":\"firewall_partial_patch\"}\n");
            return;
        }
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"firewall_action_failed\"}\n");
        return;
    }
    if (changed_files > 0) {
        record_agent_write(config, runtime, "ipv6_firewall", action);
    }
    send_firewall_status_body(client_fd, config, "ipv6", state, exists, changed_files);
}

static void handle_firewall_action(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request,
    const char *action,
    const char *confirmation
)
{
    char state[32] = "unknown";
    int exists = 0;
    int changed_files = 0;
    int ok;

    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!maintenance_firewall_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return;
    }
    if (!confirm_matches(request, confirmation)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return;
    }
    ok = strcmp(action, "apply") == 0
        ? firewall_apply(config, &exists, &changed_files, state, sizeof(state))
        : firewall_restore(config, &exists, &changed_files, state, sizeof(state));
    if (!ok) {
        if (strcmp(state, "partial") == 0) {
            send_json(client_fd, 409, "Conflict", "{\"ok\":false,\"error\":\"firewall_partial_patch\"}\n");
            return;
        }
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"firewall_action_failed\"}\n");
        return;
    }
    if (changed_files > 0) {
        record_agent_write(config, runtime, "firewall", action);
    }
    send_firewall_status_body(client_fd, config, "ipv4", state, exists, changed_files);
}

static void send_qml_patch_script_response(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const char *action,
    int records_write
)
{
    char output[4096];
    char *start;

    if (access(config->maintenance_qml_patch_script, X_OK) != 0) {
        send_json(
            client_fd,
            502,
            "Bad Gateway",
            "{\"ok\":false,\"available\":false,\"state\":\"script_missing\"}\n"
        );
        return;
    }
    if (!run_command_capture(
        config->maintenance_qml_patch_script,
        action,
        output,
        sizeof(output),
        10000,
        NULL
    )) {
        send_json(
            client_fd,
            502,
            "Bad Gateway",
            "{\"ok\":false,\"available\":false,\"state\":\"script_failed\"}\n"
        );
        return;
    }
    start = (char *)trim_ascii(output);
    if (start[0] != '{') {
        send_json(
            client_fd,
            502,
            "Bad Gateway",
            "{\"ok\":false,\"available\":false,\"state\":\"invalid_script_response\"}\n"
        );
        return;
    }
    if (records_write) {
        int changed_files = 1;
        (void)json_int_field(start, "changed_files", &changed_files);
        if (changed_files > 0) {
            record_agent_write(config, runtime, "qml_patch", action);
        }
    }
    send_json(client_fd, 200, "OK", start);
}

static void handle_qml_patch_status(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!maintenance_qml_patch_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return;
    }
    send_qml_patch_script_response(client_fd, config, NULL, "status", 0);
}

static void handle_qml_patch_action(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request,
    const char *action,
    const char *confirmation
)
{
    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!maintenance_qml_patch_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return;
    }
    if (!confirm_matches(request, confirmation)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return;
    }
    send_qml_patch_script_response(client_fd, config, runtime, action, 1);
}

static void handle_gui_reload(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    char output[1024];
    char *start;

    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!maintenance_gui_reload_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return;
    }
    if (!confirm_matches(request, "reload_gui")) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return;
    }
    if (access(config->maintenance_gui_reload_script, X_OK) != 0) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"reload_script_missing\"}\n");
        return;
    }
    if (!run_command_capture(
        config->maintenance_gui_reload_script,
        "reload",
        output,
        sizeof(output),
        10000,
        NULL
    )) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"reload_failed\"}\n");
        return;
    }
    start = (char *)trim_ascii(output);
    if (start[0] == '{') {
        send_json(client_fd, 200, "OK", start);
        return;
    }
    send_json(client_fd, 200, "OK", "{\"ok\":true,\"action\":\"reload_gui\"}\n");
}

static void handle_ssh_get(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!maintenance_ssh_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return;
    }
    send_ssh_status(client_fd);
}

static void handle_start_ssh(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!maintenance_ssh_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return;
    }
    if (!confirm_matches(request, "start_ssh")) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return;
    }
    if (!run_detached_command("/etc/init.d/dropbear", "start", 0)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"maintenance_command_failed\"}\n");
        return;
    }
    send_json(client_fd, 200, "OK", "{\"ok\":true,\"action\":\"ssh_start\",\"enabled\":true,\"running\":true}\n");
}

static void handle_stop_ssh(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!maintenance_ssh_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return;
    }
    if (!confirm_matches(request, "stop_ssh")) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return;
    }
    if (!run_detached_command("/etc/init.d/dropbear", "stop", 0)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"maintenance_command_failed\"}\n");
        return;
    }
    send_json(client_fd, 200, "OK", "{\"ok\":true,\"action\":\"ssh_stop\",\"enabled\":false,\"running\":false}\n");
}

static void handle_ssh_set(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    int enabled = 0;
    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!maintenance_ssh_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return;
    }
    if (!json_bool_field(request->body, "enabled", &enabled)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_ssh_enabled_required\"}\n");
        return;
    }
    if (!run_detached_command("/etc/init.d/dropbear", enabled ? "start" : "stop", 0)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"maintenance_command_failed\"}\n");
        return;
    }
    send_ssh_status(client_fd);
}

static void handle_reboot(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!config->maintenance_reboot_enabled) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return;
    }
    if (!confirm_matches(request, "reboot")) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return;
    }
    if (config->maintenance_ssh_start_enabled) {
        (void)run_detached_command("/etc/init.d/dropbear", "start", 0);
    }
    if (!run_detached_command("/sbin/reboot", NULL, config->maintenance_reboot_delay_ms)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"maintenance_command_failed\"}\n");
        return;
    }
    send_json(client_fd, 202, "Accepted", "{\"ok\":true,\"action\":\"reboot\",\"scheduled\":true}\n");
}

static void handle_remove_agent(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!maintenance_agent_remove_supported(config)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"maintenance_disabled\"}\n");
        return;
    }
    if (!confirm_matches(request, "remove_agent")) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return;
    }
    if (config->maintenance_ssh_start_enabled) {
        (void)run_detached_command("/etc/init.d/dropbear", "start", 0);
    }
    if (!run_detached_command(config->maintenance_agent_remove_script, "remove", 500)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"maintenance_command_failed\"}\n");
        return;
    }
    send_json(client_fd, 202, "Accepted", "{\"ok\":true,\"action\":\"remove_agent\",\"scheduled\":true,\"ssh_kept_running\":true}\n");
}

static void handle_agent_update_status(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
)
{
    char bundle_hash[C300X_AGENT_BUNDLE_HASH_LEN];
    char agent_version[C300X_MAX_VERSION_LEN];
    char api_version[16];
    char bundle_hash_json[C300X_JSON_QUOTED_LEN(C300X_AGENT_BUNDLE_HASH_LEN)];
    char agent_version_json[C300X_JSON_QUOTED_LEN(C300X_MAX_VERSION_LEN)];
    char api_version_json[64];
    char stage_dir[C300X_MAX_PATH_LEN];
    int staged = 0;
    char body[512];

    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    (void)read_agent_bundle_metadata(
        config,
        bundle_hash,
        sizeof(bundle_hash),
        agent_version,
        sizeof(agent_version),
        api_version,
        sizeof(api_version)
    );
    if (agent_update_stage_dir(config, stage_dir, sizeof(stage_dir))) {
        staged = path_is_directory(stage_dir);
    }
    json_string(bundle_hash, bundle_hash_json, sizeof(bundle_hash_json));
    json_string(agent_version, agent_version_json, sizeof(agent_version_json));
    json_string(api_version, api_version_json, sizeof(api_version_json));
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"supported\":true,\"version\":\"%s\",\"api_version\":\"1\",\"installed_bundle_hash\":%s,\"installed_agent_version\":%s,\"installed_bundle_api_version\":%s,\"staged\":%s}\n",
        C300X_NATIVE_AGENT_VERSION,
        bundle_hash_json,
        agent_version_json,
        api_version_json,
        staged ? "true" : "false"
    );
    send_json(client_fd, 200, "OK", body);
}

static void handle_agent_update_prepare(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    char bundle_hash[C300X_AGENT_BUNDLE_HASH_LEN];
    char agent_version[C300X_MAX_VERSION_LEN];
    char stage_dir[C300X_MAX_PATH_LEN];
    char bundle_hash_json[C300X_JSON_QUOTED_LEN(C300X_AGENT_BUNDLE_HASH_LEN)];
    char agent_version_json[C300X_JSON_QUOTED_LEN(C300X_MAX_VERSION_LEN)];
    char body[384];

    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    json_string_field(request->body, "bundle_hash", bundle_hash, sizeof(bundle_hash));
    json_string_field(request->body, "agent_version", agent_version, sizeof(agent_version));
    if (strncmp(bundle_hash, "sha256:", strlen("sha256:")) != 0 || agent_version[0] == '\0') {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_update_metadata\"}\n");
        return;
    }
    if (!agent_update_stage_dir(config, stage_dir, sizeof(stage_dir))) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"invalid_agent_dir\"}\n");
        return;
    }
    if (!remove_tree(stage_dir) || !mkdir_p(stage_dir, 0700)) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"stage_prepare_failed\"}\n");
        return;
    }
    record_agent_write(config, runtime, "agent_update", "prepare");
    json_string(bundle_hash, bundle_hash_json, sizeof(bundle_hash_json));
    json_string(agent_version, agent_version_json, sizeof(agent_version_json));
    snprintf(
        body,
        sizeof(body),
        "{\"ok\":true,\"prepared\":true,\"bundle_hash\":%s,\"agent_version\":%s}\n",
        bundle_hash_json,
        agent_version_json
    );
    send_json(client_fd, 200, "OK", body);
}

static void handle_agent_update_file(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    struct agent_update_file_workspace {
        char bundle_path[C300X_MAX_PATH_LEN];
        char stage_path[C300X_MAX_PATH_LEN];
        char data_text[REQUEST_BUFFER_SIZE];
        unsigned char decoded[REQUEST_BUFFER_SIZE];
        char bundle_path_json[C300X_MAX_PATH_JSON_LEN];
        char body[2048];
    };
    struct agent_update_file_workspace *workspace;
    char sha256[65];
    char mode_text[8];
    size_t decoded_len = 0;
    mode_t mode;
    int offset = 0;
    int final = 0;

    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    workspace = calloc(1, sizeof(*workspace));
    if (workspace == NULL) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        return;
    }
    json_string_field(request->body, "path", workspace->bundle_path, sizeof(workspace->bundle_path));
    json_string_field(request->body, "sha256", sha256, sizeof(sha256));
    json_string_field(request->body, "mode", mode_text, sizeof(mode_text));
    json_string_field(request->body, "data", workspace->data_text, sizeof(workspace->data_text));
    (void)json_bool_field(request->body, "final", &final);
    if (
        !json_int_field(request->body, "offset", &offset)
        || !agent_update_stage_path(config, workspace->bundle_path, workspace->stage_path, sizeof(workspace->stage_path))
        || !parse_file_mode(mode_text, 0600, &mode)
    ) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_update_file\"}\n");
        free(workspace);
        return;
    }
    if (!base64_decode_bytes(workspace->data_text, workspace->decoded, sizeof(workspace->decoded), &decoded_len)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_update_data\"}\n");
        free(workspace);
        return;
    }
    if (!write_binary_chunk(workspace->stage_path, workspace->decoded, decoded_len, offset, mode)) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"update_file_write_failed\"}\n");
        free(workspace);
        return;
    }
    record_agent_write(config, runtime, "agent_update", "upload_chunk");
    if (final && !sha256_hex_matches(workspace->stage_path, sha256)) {
        (void)unlink(workspace->stage_path);
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"update_file_hash_mismatch\"}\n");
        free(workspace);
        return;
    }
    json_string(workspace->bundle_path, workspace->bundle_path_json, sizeof(workspace->bundle_path_json));
    snprintf(
        workspace->body,
        sizeof(workspace->body),
        "{\"ok\":true,\"path\":%s,\"offset\":%d,\"bytes\":%zu,\"final\":%s}\n",
        workspace->bundle_path_json,
        offset,
        decoded_len,
        final ? "true" : "false"
    );
    send_json(client_fd, 200, "OK", workspace->body);
    free(workspace);
}

static int agent_update_manifest_sha_for_path(
    const char *manifest,
    const char *bundle_path,
    char *sha256,
    size_t sha256_len
)
{
    const char *found;

    if (sha256_len > 0) {
        sha256[0] = '\0';
    }
    found = strstr(manifest, bundle_path);
    if (found == NULL) {
        return 0;
    }
    json_string_field(found, "sha256", sha256, sha256_len);
    return sha256[0] != '\0';
}

static int apply_agent_update_file(
    const struct c300x_config *config,
    const char *manifest,
    const char *bundle_path,
    mode_t fallback_mode,
    struct agent_update_change_summary *summary
)
{
    char stage_path[C300X_MAX_PATH_LEN];
    char target_path[C300X_MAX_PATH_LEN];
    char sha256[65];
    int changed = 0;

    if (
        !agent_update_stage_path(config, bundle_path, stage_path, sizeof(stage_path))
        || !agent_update_target_path(config, bundle_path, target_path, sizeof(target_path))
    ) {
        return 0;
    }
    if (access(stage_path, F_OK) != 0) {
        return 0;
    }
    if (
        strcmp(bundle_path, "device_agent/bundle.json") != 0
        && (
            !agent_update_manifest_sha_for_path(manifest, bundle_path, sha256, sizeof(sha256))
            || !sha256_hex_matches(stage_path, sha256)
        )
    ) {
        return 0;
    }
    if (strcmp(bundle_path, "device_agent/init/c300x-native-agent") == 0) {
        if (!apply_agent_update_init_script(config, stage_path, &changed)) {
            return 0;
        }
        if (changed && summary != NULL) {
            summary->changed_files++;
            summary->script_changed = 1;
        }
        return 1;
    }
    if (!copy_binary_file_if_changed(stage_path, target_path, fallback_mode, &changed)) {
        return 0;
    }
    if (changed && summary != NULL) {
        summary->changed_files++;
        if (strcmp(bundle_path, "device_agent/armhf/c300x-agent-native") == 0) {
            summary->runtime_changed = 1;
        } else if (strcmp(bundle_path, "device_agent/scripts/qml_patch.sh") == 0) {
            summary->script_changed = 1;
            summary->qml_patch_changed = 1;
        } else if (strcmp(bundle_path, "device_agent/scripts/remove_agent.sh") == 0) {
            summary->script_changed = 1;
        } else if (strcmp(bundle_path, "device_agent/init/c300x-native-agent") == 0) {
            summary->script_changed = 1;
        } else if (strcmp(bundle_path, "device_agent/bundle.json") == 0) {
            summary->manifest_changed = 1;
        } else if (strncmp(bundle_path, "device_agent/qml/", strlen("device_agent/qml/")) == 0) {
            summary->qml_patch_changed = 1;
        }
    }
    return 1;
}

static int render_agent_init_script(
    const struct c300x_config *config,
    const char *source_path,
    const char *rendered_path
)
{
    struct render_init_workspace {
        char source[8192];
        char rendered[8192];
    };
    struct render_init_workspace *workspace = calloc(1, sizeof(*workspace));
    char base[C300X_MAX_PATH_LEN];
    const char *needle = "DEFAULT_AGENT_DIR=\"/home/bticino/cfg/extra/c300x-native-agent\"";
    const char *found;
    int truncated = 0;
    size_t prefix_len;

    if (workspace == NULL) {
        return 0;
    }
    if (
        !agent_base_dir(config, base, sizeof(base))
        || !read_bounded_text_file(source_path, workspace->source, sizeof(workspace->source), &truncated)
        || truncated
    ) {
        free(workspace);
        return 0;
    }
    found = strstr(workspace->source, needle);
    if (found == NULL) {
        free(workspace);
        return 0;
    }
    prefix_len = (size_t)(found - workspace->source);
    if (
        snprintf(
            workspace->rendered,
            sizeof(workspace->rendered),
            "%.*sDEFAULT_AGENT_DIR=\"%s\"%s",
            (int)prefix_len,
            workspace->source,
            base,
            found + strlen(needle)
        ) >= (int)sizeof(workspace->rendered)
    ) {
        free(workspace);
        return 0;
    }
    int ok = write_binary_chunk(
        rendered_path,
        (const unsigned char *)workspace->rendered,
        strlen(workspace->rendered),
        0,
        0700
    );
    free(workspace);
    return ok;
}

static int ensure_agent_init_link(void)
{
    char current[C300X_MAX_PATH_LEN];
    ssize_t len = readlink(C300X_AGENT_INIT_LINK, current, sizeof(current) - 1);

    if (len >= 0) {
        current[len] = '\0';
        if (strcmp(current, C300X_AGENT_INIT_SCRIPT) == 0) {
            return 1;
        }
        (void)unlink(C300X_AGENT_INIT_LINK);
    }
    return symlink(C300X_AGENT_INIT_SCRIPT, C300X_AGENT_INIT_LINK) == 0 || errno == EEXIST;
}

static int agent_init_link_matches(void)
{
    char current[C300X_MAX_PATH_LEN];
    ssize_t len = readlink(C300X_AGENT_INIT_LINK, current, sizeof(current) - 1);

    if (len < 0) {
        return 0;
    }
    current[len] = '\0';
    return strcmp(current, C300X_AGENT_INIT_SCRIPT) == 0;
}

static int apply_agent_update_init_script(
    const struct c300x_config *config,
    const char *stage_path,
    int *changed
)
{
    char rendered_path[C300X_MAX_PATH_LEN + 16];
    int content_changed;
    int link_changed;

    if (changed != NULL) {
        *changed = 0;
    }
    if (snprintf(rendered_path, sizeof(rendered_path), "%s.rendered", stage_path) >= (int)sizeof(rendered_path)) {
        return 0;
    }
    if (!render_agent_init_script(config, stage_path, rendered_path)) {
        (void)unlink(rendered_path);
        return 0;
    }
    content_changed = !file_content_matches(rendered_path, C300X_AGENT_INIT_SCRIPT);
    link_changed = !agent_init_link_matches();
    if (!content_changed && !link_changed) {
        (void)unlink(rendered_path);
        return 1;
    }
    {
        int status = system("mount -o remount,rw / >/dev/null 2>&1");
        (void)status;
    }
    if (
        (content_changed && !copy_binary_file(rendered_path, C300X_AGENT_INIT_SCRIPT, 0700))
        || !ensure_agent_init_link()
    ) {
        (void)unlink(rendered_path);
        {
            int status = system("mount -o remount,ro / >/dev/null 2>&1");
            (void)status;
        }
        return 0;
    }
    {
        int status = system("mount -o remount,ro / >/dev/null 2>&1");
        (void)status;
    }
    (void)unlink(rendered_path);
    if (changed != NULL) {
        *changed = 1;
    }
    return 1;
}

static int apply_agent_update_files(
    const struct c300x_config *config,
    const char *manifest,
    const char *installed_manifest,
    struct agent_update_change_summary *summary
)
{
    static const struct {
        const char *bundle_path;
        mode_t mode;
    } files[] = {
        {"device_agent/armhf/c300x-agent-native", 0700},
        {"device_agent/scripts/qml_patch.sh", 0700},
        {"device_agent/scripts/remove_agent.sh", 0700},
        {"device_agent/scripts/bootstrap_firewall.sh", 0700},
        {"device_agent/qml/Alarm.qml", 0644},
        {"device_agent/qml/HomeAssistant.qml", 0644},
        {"device_agent/qml/js/c300x_ha.js", 0644},
        {"device_agent/qml/js/c300x_i18n.js", 0644},
        {"device_agent/qml/js/c300x_memos.js", 0644},
        {"device_agent/bundle.json", 0600},
    };

    if (summary != NULL) {
        memset(summary, 0, sizeof(*summary));
        summary->runtime_changed = agent_update_manifest_field_changed(
            installed_manifest,
            manifest,
            "runtime_hash"
        );
        summary->qml_patch_changed = agent_update_manifest_field_changed(
            installed_manifest,
            manifest,
            "qml_patch_hash"
        );
        summary->script_changed = agent_update_manifest_field_changed(
            installed_manifest,
            manifest,
            "script_hash"
        );
        summary->firewall_patch_changed = agent_update_manifest_field_changed(
            installed_manifest,
            manifest,
            "firewall_patch_hash"
        );
        summary->ipv6_firewall_patch_changed = agent_update_manifest_field_changed(
            installed_manifest,
            manifest,
            "ipv6_firewall_patch_hash"
        );
        summary->config_schema_changed = agent_update_manifest_field_changed(
            installed_manifest,
            manifest,
            "config_schema_hash"
        );
    }
    for (size_t index = 0; index < sizeof(files) / sizeof(files[0]); index++) {
        if (
            !apply_agent_update_file(
                config,
                manifest,
                files[index].bundle_path,
                files[index].mode,
                summary
            )
        ) {
            return 0;
        }
    }
    return 1;
}

static void handle_agent_update_apply(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    struct agent_update_apply_workspace {
        char bundle_hash[C300X_AGENT_BUNDLE_HASH_LEN];
        char staged_bundle_hash[C300X_AGENT_BUNDLE_HASH_LEN];
        char staged_manifest[C300X_MAX_PATH_LEN];
        char installed_manifest_path[C300X_MAX_PATH_LEN];
        char installed_manifest[8192];
        char manifest[8192];
        char stage_dir[C300X_MAX_PATH_LEN];
        char body[512];
    };
    struct agent_update_apply_workspace *workspace;
    int truncated = 0;
    int installed_truncated = 0;
    struct agent_update_change_summary summary;

    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!confirm_matches(request, "update_agent")) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return;
    }
    workspace = calloc(1, sizeof(*workspace));
    if (workspace == NULL) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        return;
    }
    json_string_field(request->body, "bundle_hash", workspace->bundle_hash, sizeof(workspace->bundle_hash));
    if (strncmp(workspace->bundle_hash, "sha256:", strlen("sha256:")) != 0) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_update_metadata\"}\n");
        free(workspace);
        return;
    }
    if (
        !agent_update_stage_path(
            config,
            "device_agent/bundle.json",
            workspace->staged_manifest,
            sizeof(workspace->staged_manifest)
        )
    ) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"invalid_agent_dir\"}\n");
        free(workspace);
        return;
    }
    if (
        !read_bounded_text_file(
            workspace->staged_manifest,
            workspace->manifest,
            sizeof(workspace->manifest),
            &truncated
        )
        || truncated
    ) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"update_manifest_missing\"}\n");
        free(workspace);
        return;
    }
    json_string_field(
        workspace->manifest,
        "bundle_hash",
        workspace->staged_bundle_hash,
        sizeof(workspace->staged_bundle_hash)
    );
    if (
        !constant_time_equal(
            workspace->staged_bundle_hash,
            strlen(workspace->staged_bundle_hash),
            workspace->bundle_hash
        )
    ) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"update_bundle_hash_mismatch\"}\n");
        free(workspace);
        return;
    }
    if (
        agent_bundle_manifest_path(
            config,
            workspace->installed_manifest_path,
            sizeof(workspace->installed_manifest_path)
        )
        && !read_bounded_text_file(
            workspace->installed_manifest_path,
            workspace->installed_manifest,
            sizeof(workspace->installed_manifest),
            &installed_truncated
        )
    ) {
        workspace->installed_manifest[0] = '\0';
    }
    if (installed_truncated) {
        workspace->installed_manifest[0] = '\0';
    }
    if (!apply_agent_update_files(config, workspace->manifest, workspace->installed_manifest, &summary)) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"update_apply_failed\"}\n");
        free(workspace);
        return;
    }
    if (agent_update_stage_dir(config, workspace->stage_dir, sizeof(workspace->stage_dir))) {
        (void)remove_tree(workspace->stage_dir);
    }
    record_agent_write(config, runtime, "agent_update", "apply");
    if (summary.runtime_changed) {
        (void)run_detached_command("/etc/init.d/c300x-native-agent", "restart", 500);
    }
    snprintf(
        workspace->body,
        sizeof(workspace->body),
        "{\"ok\":true,\"action\":\"agent_update\",\"restart_scheduled\":%s,\"changed_files\":%d,\"runtime_changed\":%s,\"qml_patch_changed\":%s,\"script_changed\":%s,\"firewall_patch_changed\":%s,\"ipv6_firewall_patch_changed\":%s,\"config_schema_changed\":%s,\"manifest_changed\":%s}\n",
        summary.runtime_changed ? "true" : "false",
        summary.changed_files,
        summary.runtime_changed ? "true" : "false",
        summary.qml_patch_changed ? "true" : "false",
        summary.script_changed ? "true" : "false",
        summary.firewall_patch_changed ? "true" : "false",
        summary.ipv6_firewall_patch_changed ? "true" : "false",
        summary.config_schema_changed ? "true" : "false",
        summary.manifest_changed ? "true" : "false"
    );
    send_json(
        client_fd,
        summary.runtime_changed ? 202 : 200,
        summary.runtime_changed ? "Accepted" : "OK",
        workspace->body
    );
    free(workspace);
}

static void handle_config_normalize(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    char error[C300X_MAX_ERROR_LEN];
    char error_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ERROR_LEN)];
    char body[384];
    int changed = 0;

    if (!maintenance_authorized(config, request)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
        return;
    }
    if (!confirm_matches(request, "normalize_config")) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"maintenance_confirmation_required\"}\n");
        return;
    }
    if (!c300x_save_config_if_changed(config, error, sizeof(error), &changed)) {
        json_string(error, error_json, sizeof(error_json));
        snprintf(
            body,
            sizeof(body),
            "{\"ok\":false,\"error\":\"config_save_failed\",\"detail\":%s}\n",
            error_json
        );
        send_json(client_fd, 500, "Internal Server Error", body);
        return;
    }
    if (changed) {
        record_agent_write(config, runtime, "config", "normalize");
    }
    send_json(
        client_fd,
        200,
        "OK",
        changed
            ? "{\"ok\":true,\"action\":\"normalize_config\",\"changed\":true}\n"
            : "{\"ok\":true,\"action\":\"normalize_config\",\"changed\":false}\n"
    );
}

static void handle_api_request(
    int client_fd,
    struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    if (strcmp(request->method, "GET") == 0 && (
        strcmp(request->path, "/") == 0
        || strcmp(request->path, "/setup") == 0
    )) {
        if (config->api_no_auth) {
            handle_setup_page(client_fd);
        } else {
            send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"setup_disabled\"}\n");
        }
        return;
    }

    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/health") == 0) {
        send_json(client_fd, 200, "OK", "{\"ok\":true,\"agent\":\"native-c\",\"version\":\"" C300X_NATIVE_AGENT_VERSION "\"}\n");
        return;
    }

    if (strcmp(request->path, "/api/v1/maintenance/auth") == 0) {
        if (strcmp(request->method, "GET") == 0) {
            if (!auth_config_read_authorized(config, request)) {
                send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
                return;
            }
            handle_auth_config_get(client_fd, config);
            return;
        }
        if (strcmp(request->method, "POST") == 0) {
            handle_auth_config_post(client_fd, config, runtime, request);
            return;
        }
    }

    if (!api_request_authorized(config, request)) {
        send_auth_required(client_fd);
        return;
    }

    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/capabilities") == 0) {
        api_capabilities(client_fd, config);
        return;
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/state") == 0) {
        api_state(client_fd, config, runtime);
        return;
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/display-bridge") == 0) {
        handle_display_bridge_status(client_fd, config, runtime);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/display-bridge") == 0) {
        handle_display_bridge_post(client_fd, runtime, config, request);
        return;
    }
    if (
        strcmp(request->method, "POST") == 0
        && strcmp(request->path, "/api/v1/display-bridge/events") == 0
    ) {
        handle_display_bridge_event_post(client_fd, config, runtime, request);
        return;
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/events/recent") == 0) {
        handle_recent_events_get(client_fd, runtime);
        return;
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/events/subscriptions") == 0) {
        handle_subscriptions_get(client_fd, runtime);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/events/subscriptions") == 0) {
        handle_subscriptions_post(client_fd, runtime, config, request);
        return;
    }
    if (strncmp(request->path, "/api/v1/events/subscriptions/", strlen("/api/v1/events/subscriptions/")) == 0) {
        const char *id = request->path + strlen("/api/v1/events/subscriptions/");
        if (strcmp(request->method, "DELETE") == 0) {
            handle_subscription_delete(client_fd, runtime, config, id);
            return;
        }
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/system/metrics") == 0) {
        handle_system_metrics(client_fd, runtime);
        return;
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/diagnostics") == 0) {
        handle_diagnostics_get(client_fd, runtime);
        return;
    }

    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/stair-light/actions/activate") == 0) {
        handle_stair_light(client_fd, config, runtime, request);
        return;
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/smartphone-forwarding") == 0) {
        handle_smartphone_get(client_fd, config);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/smartphone-forwarding") == 0) {
        handle_smartphone_post(client_fd, config, request);
        return;
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/ringer") == 0) {
        handle_ringer_get(client_fd, config);
        return;
    }
    if (
        strcmp(request->method, "GET") == 0
        && (strcmp(request->path, "/api/v1/video/doorbell") == 0
            || strcmp(request->path, "/api/v1/video/doorbell/status") == 0)
    ) {
        handle_doorbell_video_get(client_fd, config, runtime);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/video/doorbell/actions/activate") == 0) {
        handle_doorbell_video_activate(client_fd, runtime, request);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/video/doorbell/actions/stop") == 0) {
        handle_doorbell_video_stop(client_fd, runtime);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/ringer") == 0) {
        handle_ringer_post(client_fd, config, request);
        return;
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/answering-machine") == 0) {
        handle_answering_get(client_fd, config);
        return;
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/answering-machine/messages") == 0) {
        handle_answering_messages_get(client_fd, runtime);
        return;
    }
    if (strncmp(request->path, "/api/v1/answering-machine/messages/", strlen("/api/v1/answering-machine/messages/")) == 0) {
        const char *message_id = request->path + strlen("/api/v1/answering-machine/messages/");
        const char *suffix = strstr(message_id, "/video");
        if (strcmp(request->method, "GET") == 0 && suffix != NULL && suffix[6] == '\0') {
            char decoded_message_id[C300X_MAX_VOICEMAIL_ID_LEN];
            size_t id_len = (size_t)(suffix - message_id);
            if (id_len >= sizeof(decoded_message_id)) {
                send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_message_id\"}\n");
                return;
            }
            memcpy(decoded_message_id, message_id, id_len);
            decoded_message_id[id_len] = '\0';
            handle_answering_message_video_get(client_fd, runtime, decoded_message_id);
            return;
        }
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/answering-machine/messages/actions/delete") == 0) {
        handle_answering_message_delete(client_fd, config, runtime, request);
        return;
    }
    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/api/v1/memos") == 0) {
        handle_memos_get(client_fd, runtime);
        return;
    }
    if (strncmp(request->path, "/api/v1/memos/voice/", strlen("/api/v1/memos/voice/")) == 0) {
        const char *memo_entry = request->path + strlen("/api/v1/memos/voice/");
        const char *suffix = strstr(memo_entry, "/audio");
        if (strcmp(request->method, "GET") == 0 && suffix != NULL && suffix[6] == '\0') {
            char decoded_memo_entry[C300X_MAX_VOICEMAIL_ID_LEN];
            size_t id_len = (size_t)(suffix - memo_entry);
            if (id_len >= sizeof(decoded_memo_entry)) {
                send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_memo_id\"}\n");
                return;
            }
            percent_decode_query_value(
                memo_entry,
                memo_entry + id_len,
                decoded_memo_entry,
                sizeof(decoded_memo_entry)
            );
            handle_memo_audio_get(client_fd, runtime, decoded_memo_entry);
            return;
        }
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/memos/actions/delete") == 0) {
        handle_memos_delete(client_fd, config, runtime, request);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/answering-machine") == 0) {
        handle_answering_post(client_fd, config, request);
        return;
    }
    if (strncmp(request->path, "/api/v1/locks/", strlen("/api/v1/locks/")) == 0) {
        const char *lock_id = request->path + strlen("/api/v1/locks/");
        const char *suffix = strstr(lock_id, "/actions/unlock");
        if (strcmp(request->method, "POST") == 0 && suffix != NULL && suffix[15] == '\0') {
            char decoded_lock_id[C300X_MAX_LOCK_ID_LEN];
            size_t id_len = (size_t)(suffix - lock_id);
            if (id_len >= sizeof(decoded_lock_id)) {
                send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_lock_id\"}\n");
                return;
            }
            memcpy(decoded_lock_id, lock_id, id_len);
            decoded_lock_id[id_len] = '\0';
            handle_unlock(client_fd, config, decoded_lock_id);
            return;
        }
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/ssh/actions/start") == 0) {
        handle_start_ssh(client_fd, config, request);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/ssh/actions/stop") == 0) {
        handle_stop_ssh(client_fd, config, request);
        return;
    }
    if (strcmp(request->path, "/api/v1/maintenance/ssh") == 0) {
        if (strcmp(request->method, "GET") == 0) {
            handle_ssh_get(client_fd, config, request);
            return;
        }
        if (strcmp(request->method, "POST") == 0) {
            handle_ssh_set(client_fd, config, request);
            return;
        }
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/reboot") == 0) {
        handle_reboot(client_fd, config, request);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/agent/actions/remove") == 0) {
        handle_remove_agent(client_fd, config, request);
        return;
    }
    if (strcmp(request->path, "/api/v1/maintenance/update/status") == 0) {
        if (strcmp(request->method, "GET") == 0) {
            handle_agent_update_status(client_fd, config, request);
            return;
        }
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/update/prepare") == 0) {
        handle_agent_update_prepare(client_fd, config, runtime, request);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/update/file") == 0) {
        handle_agent_update_file(client_fd, config, runtime, request);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/update/apply") == 0) {
        handle_agent_update_apply(client_fd, config, runtime, request);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/config/actions/normalize") == 0) {
        handle_config_normalize(client_fd, config, runtime, request);
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/mqtt/actions/migrate-legacy") == 0) {
        handle_mqtt_migrate_legacy_post(client_fd, config, runtime, request);
        return;
    }
    if (strcmp(request->path, "/api/v1/maintenance/mqtt") == 0) {
        if (strcmp(request->method, "GET") == 0) {
            if (!maintenance_authorized(config, request)) {
                send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
                return;
            }
            handle_mqtt_status(client_fd, config, runtime);
            return;
        }
        if (strcmp(request->method, "POST") == 0) {
            handle_mqtt_post(client_fd, config, runtime, request);
            return;
        }
    }
    if (strcmp(request->path, "/api/v1/maintenance/legacy-mqtt") == 0) {
        if (strcmp(request->method, "GET") == 0) {
            if (!maintenance_authorized(config, request)) {
                send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"maintenance_unauthorized\"}\n");
                return;
            }
            handle_legacy_mqtt_status(client_fd, config);
            return;
        }
        if (strcmp(request->method, "POST") == 0) {
            handle_legacy_mqtt_post(client_fd, config, runtime, request);
            return;
        }
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/gui/actions/reload") == 0) {
        handle_gui_reload(client_fd, config, request);
        return;
    }
    if (strcmp(request->path, "/api/v1/maintenance/firewall") == 0) {
        if (strcmp(request->method, "GET") == 0) {
            handle_firewall_status(client_fd, config, request);
            return;
        }
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/firewall/actions/apply") == 0) {
        handle_firewall_action(
            client_fd,
            config,
            runtime,
            request,
            "apply",
            "apply_firewall"
        );
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/firewall/actions/restore") == 0) {
        handle_firewall_action(
            client_fd,
            config,
            runtime,
            request,
            "restore",
            "restore_firewall"
        );
        return;
    }
    if (strcmp(request->path, "/api/v1/maintenance/ipv6-firewall") == 0) {
        if (strcmp(request->method, "GET") == 0) {
            handle_ipv6_firewall_status(client_fd, config, request);
            return;
        }
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/ipv6-firewall/actions/apply") == 0) {
        handle_ipv6_firewall_action(
            client_fd,
            config,
            runtime,
            request,
            "apply",
            "apply_ipv6_firewall"
        );
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/ipv6-firewall/actions/restore") == 0) {
        handle_ipv6_firewall_action(
            client_fd,
            config,
            runtime,
            request,
            "restore",
            "restore_ipv6_firewall"
        );
        return;
    }
    if (strcmp(request->path, "/api/v1/maintenance/qml-patch") == 0) {
        if (strcmp(request->method, "GET") == 0) {
            handle_qml_patch_status(client_fd, config, request);
            return;
        }
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/qml-patch/actions/apply") == 0) {
        handle_qml_patch_action(
            client_fd,
            config,
            runtime,
            request,
            "apply",
            "apply_qml_patch"
        );
        return;
    }
    if (strcmp(request->method, "POST") == 0 && strcmp(request->path, "/api/v1/maintenance/qml-patch/actions/restore") == 0) {
        handle_qml_patch_action(
            client_fd,
            config,
            runtime,
            request,
            "restore",
            "restore_qml_patch"
        );
        return;
    }

    send_json(client_fd, 501, "Not Implemented", "{\"ok\":false,\"error\":\"not_implemented\"}\n");
}

static int handle_ui_request(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    if (strcmp(request->method, "GET") != 0) {
        send_json(client_fd, 405, "Method Not Allowed", "{\"ok\":false,\"error\":\"method_not_allowed\"}\n");
        return 1;
    }

    if (strcmp(request->method, "GET") == 0 && strcmp(request->path, "/health") == 0) {
        send_json(client_fd, 200, "OK", "{\"ok\":true,\"bridge\":\"native-c\",\"version\":\"" C300X_NATIVE_AGENT_VERSION "\"}\n");
        return 1;
    }

    if (strcmp(request->path, "/ui/memos") == 0) {
        if (!client_is_loopback(client_fd)) {
            send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"loopback_required\"}\n");
            return 1;
        }
        handle_memos_get(client_fd, runtime);
        return 1;
    }

    if (strcmp(request->path, "/ui/answering-machine/messages") == 0) {
        if (!client_is_loopback(client_fd)) {
            send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"loopback_required\"}\n");
            return 1;
        }
        handle_answering_messages_get(client_fd, runtime);
        return 1;
    }

    if (strcmp(request->path, "/ui/events/status") == 0) {
        if (!client_is_loopback(client_fd)) {
            send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"loopback_required\"}\n");
            return 1;
        }
        handle_ui_events_status(client_fd, runtime);
        return 1;
    }

    if (strcmp(request->path, "/ui/events/next") == 0) {
        if (!client_is_loopback(client_fd)) {
            send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"loopback_required\"}\n");
            return 1;
        }
        return handle_ui_events_next(client_fd, runtime, request);
    }

    if (!display_bridge_active(config, runtime)) {
        send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"display_bridge_disabled\"}\n");
        return 1;
    }
    if (!client_is_loopback(client_fd)) {
        send_json(client_fd, 403, "Forbidden", "{\"ok\":false,\"error\":\"loopback_required\"}\n");
        return 1;
    }

    if (strcmp(request->path, "/ui/state") == 0 || strcmp(request->path, "/ui/alarm/status") == 0) {
        char payload[128];
        char *response = allocate_response_buffer(client_fd, C300X_LARGE_RESPONSE_SIZE);
        if (response == NULL) {
            return 1;
        }
        snprintf(payload, sizeof(payload), "{\"type\":\"status\"}");
        if (!forward_to_homeassistant(config, runtime, payload, response, C300X_LARGE_RESPONSE_SIZE)) {
            send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"homeassistant_unavailable\"}\n");
            free(response);
            return 1;
        }
        send_json(client_fd, 200, "OK", response);
        free(response);
        return 1;
    }

    if (strcmp(request->path, "/homeassistant") == 0) {
        handle_ui_homeassistant(client_fd, config, runtime, request);
        return 1;
    }
    if (strcmp(request->path, "/ui/action") == 0) {
        handle_ui_action(client_fd, config, runtime, request);
        return 1;
    }
    if (strcmp(request->path, "/ui/stair-light") == 0) {
        handle_ui_stair_light(client_fd, config, runtime, request);
        return 1;
    }
    if (strcmp(request->path, "/ui/alarm/command") == 0) {
        handle_ui_alarm_command(client_fd, config, runtime, request);
        return 1;
    }
    send_json(client_fd, 404, "Not Found", "{\"ok\":false,\"error\":\"not_found\"}\n");
    return 1;
}

static void handle_ui_homeassistant(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    char domain[32];
    char service[32];
    char entities[128];
    char entity_id[128];
    char payload[256];
    char *response = allocate_response_buffer(client_fd, C300X_LARGE_RESPONSE_SIZE);

    if (response == NULL) {
        return;
    }

    query_param_value(request->query, "domain", domain, sizeof(domain));
    query_param_value(request->query, "service", service, sizeof(service));
    if (!query_param_value(request->query, "entities", entities, sizeof(entities))) {
        query_param_value(request->query, "entity_id", entities, sizeof(entities));
    }

    if (domain[0] == '\0' && service[0] == '\0' && entities[0] == '\0') {
        snprintf(payload, sizeof(payload), "{\"type\":\"dashboard\"}");
        if (!forward_to_homeassistant(config, runtime, payload, response, C300X_LARGE_RESPONSE_SIZE)) {
            send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"homeassistant_unavailable\"}\n");
            free(response);
            return;
        }
        send_json(client_fd, 200, "OK", response);
        free(response);
        return;
    }

    if (strcmp(domain, C300X_DASHBOARD_DOMAIN) != 0 || strcmp(service, "toggle") != 0 || entities[0] == '\0') {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"unsupported_dashboard_command\"}\n");
        free(response);
        return;
    }

    snprintf(entity_id, sizeof(entity_id), "%s", entities);
    char *comma = strchr(entity_id, ',');
    if (comma != NULL) {
        *comma = '\0';
    }
    char *trimmed = entity_id;
    while (*trimmed == ' ') {
        trimmed++;
    }
    if (!validate_action_id(trimmed)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_action_id\"}\n");
        free(response);
        return;
    }
    if (strcmp(trimmed, C300X_DASHBOARD_STAIR_LIGHT_ENTITY) == 0) {
        snprintf(payload, sizeof(payload), "{\"type\":\"stair_light\"}");
    } else {
        snprintf(payload, sizeof(payload), "{\"type\":\"dashboard_action\",\"entity_id\":\"%s\"}", trimmed);
    }
    if (!forward_to_homeassistant(config, runtime, payload, response, C300X_LARGE_RESPONSE_SIZE)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"homeassistant_unavailable\"}\n");
        free(response);
        return;
    }
    send_json(client_fd, 200, "OK", response);
    free(response);
}

static void handle_ui_action(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    char action_id[128];
    char payload[256];
    char *response = allocate_response_buffer(client_fd, C300X_LARGE_RESPONSE_SIZE);

    if (response == NULL) {
        return;
    }
    query_param_value(request->query, "id", action_id, sizeof(action_id));
    if (action_id[0] == '\0' || !validate_action_id(action_id)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_action_id\"}\n");
        free(response);
        return;
    }
    snprintf(payload, sizeof(payload), "{\"type\":\"action\",\"action_id\":\"%s\"}", action_id);
    if (!forward_to_homeassistant(config, runtime, payload, response, C300X_LARGE_RESPONSE_SIZE)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"homeassistant_unavailable\"}\n");
        free(response);
        return;
    }
    send_json(client_fd, 200, "OK", response);
    free(response);
}

static void handle_ui_stair_light(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    char address[C300X_MAX_ADDRESS_LEN];
    char reply[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
    char body[512];
    char address_json[C300X_JSON_QUOTED_LEN(C300X_MAX_ADDRESS_LEN)];

    query_param_value(request->query, "address", address, sizeof(address));
    if (!activate_stair_light(
        config,
        runtime,
        address,
        sizeof(address),
        reply,
        sizeof(reply),
        error,
        sizeof(error)
    )) {
        if (strcmp(error, "invalid_stair_light_address") == 0) {
            send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_stair_light_address\"}\n");
            return;
        }
        send_device_error(client_fd, error);
        return;
    }
    json_string(address, address_json, sizeof(address_json));
    snprintf(body, sizeof(body), "{\"ok\":true,\"address\":%s}\n", address_json);
    send_json(client_fd, 200, "OK", body);
}

static void handle_ui_alarm_command(
    int client_fd,
    const struct c300x_config *config,
    struct agent_runtime *runtime,
    const struct request *request
)
{
    char command[32];
    char code[64];
    char force_text[8];
    char check_text[8];
    char payload[256];
    char *response = allocate_response_buffer(client_fd, C300X_LARGE_RESPONSE_SIZE);
    int force = 0;
    int check = 0;

    if (response == NULL) {
        return;
    }
    query_param_value(request->query, "command", command, sizeof(command));
    if (!validate_alarm_command(command)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_alarm_command\"}\n");
        free(response);
        return;
    }
    if (query_param_value(request->query, "force", force_text, sizeof(force_text))) {
        force = strcmp(force_text, "1") == 0 || strcmp(force_text, "true") == 0;
    }
    if (query_param_value(request->query, "check", check_text, sizeof(check_text))) {
        check = strcmp(check_text, "1") == 0 || strcmp(check_text, "true") == 0;
    }
    if (query_param_value(request->query, "code", code, sizeof(code)) && code[0] != '\0') {
        if (!validate_alarm_code(code)) {
            send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"invalid_alarm_code\"}\n");
            free(response);
            return;
        }
        snprintf(
            payload,
            sizeof(payload),
            "{\"type\":\"alarm_command\",\"command\":\"%s\",\"code\":\"%s\"%s%s}",
            command,
            code,
            force ? ",\"force\":true" : "",
            check ? ",\"check\":true" : ""
        );
    } else {
        snprintf(
            payload,
            sizeof(payload),
            "{\"type\":\"alarm_command\",\"command\":\"%s\"%s%s}",
            command,
            force ? ",\"force\":true" : "",
            check ? ",\"check\":true" : ""
        );
    }
    if (!forward_to_homeassistant(config, runtime, payload, response, C300X_LARGE_RESPONSE_SIZE)) {
        send_json(client_fd, 502, "Bad Gateway", "{\"ok\":false,\"error\":\"homeassistant_unavailable\"}\n");
        free(response);
        return;
    }
    send_json(client_fd, 200, "OK", response);
    free(response);
}

static void handle_client(
    int client_fd,
    enum listener_kind kind,
    struct c300x_config *config,
    struct agent_runtime *runtime
)
{
    struct request_workspace *workspace = malloc(sizeof(*workspace));
    struct timeval receive_timeout;
    struct timeval send_timeout;
    int too_large = 0;
    int close_client = 1;

    if (workspace == NULL) {
        send_json(client_fd, 500, "Internal Server Error", "{\"ok\":false,\"error\":\"out_of_memory\"}\n");
        close(client_fd);
        return;
    }

    receive_timeout.tv_sec = 0;
    receive_timeout.tv_usec = 500000;
    send_timeout.tv_sec = 2;
    send_timeout.tv_usec = 0;
    (void)setsockopt(
        client_fd,
        SOL_SOCKET,
        SO_RCVTIMEO,
        &receive_timeout,
        sizeof(receive_timeout)
    );
    (void)setsockopt(
        client_fd,
        SOL_SOCKET,
        SO_SNDTIMEO,
        &send_timeout,
        sizeof(send_timeout)
    );

    if (!receive_http_request(client_fd, workspace->buffer, sizeof(workspace->buffer), &too_large)) {
        if (too_large) {
            send_json(client_fd, 413, "Payload Too Large", "{\"ok\":false,\"error\":\"request_too_large\"}\n");
        }
        goto cleanup;
    }
    if (!parse_request(workspace->buffer, &workspace->request)) {
        send_json(client_fd, 400, "Bad Request", "{\"ok\":false,\"error\":\"bad_request\"}\n");
        goto cleanup;
    }

    if (kind == LISTENER_API) {
        handle_api_request(client_fd, config, runtime, &workspace->request);
    } else {
        close_client = handle_ui_request(client_fd, config, runtime, &workspace->request);
    }

cleanup:
    free(workspace);
    if (close_client) {
        close(client_fd);
    }
}

static int agent_has_home_assistant_connection(
    const struct agent_runtime *runtime,
    time_t now
)
{
    return runtime->home_assistant_connected_this_run
        && runtime->home_assistant_last_seen_at > 0
        && now - runtime->home_assistant_last_seen_at < C300X_HOME_ASSISTANT_CONNECTED_SECONDS;
}

int c300x_run(struct c300x_config *config)
{
    struct listener listeners[2];
    struct pollfd poll_fds[2 + 1 + 1 + 1 + 3 + C300X_VIDEO_MAX_POLL_FDS];
    nfds_t listener_count = 0;
    int udp_fd = -1;
    struct c300x_mdns mdns;
    struct agent_runtime *runtime = NULL;
    struct c300x_video *video = NULL;
    char video_error[C300X_MAX_ERROR_LEN];
    int ui_listener_enabled = 1;
    int result = 1;

    if (!config->api_no_auth && config->api_token[0] == '\0') {
        fprintf(stderr, "api.token must be configured when api.noAuth=false\n");
        return 2;
    }
    runtime = calloc(1, sizeof(*runtime));
    if (runtime == NULL) {
        fprintf(stderr, "failed to allocate agent runtime\n");
        return 2;
    }
    runtime->ui_event_wait_fd = -1;
    c300x_mdns_init(&mdns);
    c300x_mqtt_init(&runtime->mqtt);
    load_subscriptions(runtime, config->subscription_store_path);
    voicemail_init(runtime, config);
    memos_init(runtime, config);
    system_metrics_init(config, runtime);
    listeners[listener_count].fd = make_listener(config->listen_host, config->api_port);
    listeners[listener_count].kind = LISTENER_API;
    if (listeners[listener_count].fd < 0) {
        fprintf(stderr, "failed to bind API listener on %s:%u: %s\n", config->listen_host, config->api_port, strerror(errno));
        result = 2;
        goto cleanup;
    }
    listener_count++;

    if (ui_listener_enabled) {
        listeners[listener_count].fd = make_listener(C300X_UI_LISTEN_HOST, config->ui_port);
        listeners[listener_count].kind = LISTENER_UI;
        if (listeners[listener_count].fd < 0) {
            fprintf(stderr, "failed to bind UI listener on %s:%u: %s\n", C300X_UI_LISTEN_HOST, config->ui_port, strerror(errno));
            result = 2;
            goto cleanup;
        }
        listener_count++;
    }
    udp_fd = create_udp_event_socket(config);
    if (config->video_enabled) {
        video = c300x_video_create(config, video_error, sizeof(video_error));
        if (video == NULL) {
            fprintf(stderr, "%s\n", video_error[0] != '\0' ? video_error : "video: initialization failed");
            result = 2;
            goto cleanup;
        }
    }
    runtime->video = video;

    fprintf(stderr, "c300x native agent %s listening api=%s:%u ui=%s\n",
        C300X_NATIVE_AGENT_VERSION,
        config->listen_host,
        config->api_port,
        ui_listener_enabled ? C300X_UI_LISTEN_HOST : "disabled"
    );

    for (;;) {
        nfds_t index;
        nfds_t poll_count = listener_count;
        int udp_poll_index = -1;
        int mdns_poll_index = -1;
        int mqtt_poll_index = -1;
        int voicemail_poll_index = -1;
        int text_memos_poll_index = -1;
        int voice_memos_poll_index = -1;
        int video_poll_index = -1;
        int video_poll_count = 0;
        int poll_timeout_ms = -1;
        time_t now = time(NULL);
        int network_online = runtime_network_online(runtime, now);

        for (index = 0; index < listener_count; index++) {
            poll_fds[index].fd = listeners[index].fd;
            poll_fds[index].events = POLLIN;
            poll_fds[index].revents = 0;
        }
        c300x_mdns_open_if_needed(
            &mdns,
            config,
            agent_has_home_assistant_connection(runtime, now),
            network_online,
            now
        );
        c300x_mqtt_open_if_needed(&runtime->mqtt, config, network_online, now);
        if (udp_fd >= 0) {
            udp_poll_index = (int)poll_count;
            poll_fds[poll_count].fd = udp_fd;
            poll_fds[poll_count].events = POLLIN;
            poll_fds[poll_count].revents = 0;
            poll_count++;
        }
        if (c300x_mdns_fd(&mdns) >= 0) {
            mdns_poll_index = (int)poll_count;
            poll_fds[poll_count].fd = c300x_mdns_fd(&mdns);
            poll_fds[poll_count].events = POLLIN;
            poll_fds[poll_count].revents = 0;
            poll_count++;
            poll_timeout_ms = min_timeout_ms(
                poll_timeout_ms,
                timeout_until_ms(now, c300x_mdns_next_announce_at(&mdns))
            );
        }
        if (c300x_mqtt_fd(&runtime->mqtt) >= 0) {
            mqtt_poll_index = (int)poll_count;
            poll_fds[poll_count].fd = c300x_mqtt_fd(&runtime->mqtt);
            poll_fds[poll_count].events = POLLIN;
            poll_fds[poll_count].revents = 0;
            poll_count++;
            poll_timeout_ms = min_timeout_ms(
                poll_timeout_ms,
                c300x_mqtt_poll_timeout_ms(&runtime->mqtt, now)
            );
        } else {
            poll_timeout_ms = min_timeout_ms(
                poll_timeout_ms,
                c300x_mqtt_poll_timeout_ms(&runtime->mqtt, now)
            );
        }
        if (runtime->voicemail.inotify_fd >= 0) {
            voicemail_poll_index = (int)poll_count;
            poll_fds[poll_count].fd = runtime->voicemail.inotify_fd;
            poll_fds[poll_count].events = POLLIN;
            poll_fds[poll_count].revents = 0;
            poll_count++;
        }
        if (runtime->text_memos.inotify_fd >= 0) {
            text_memos_poll_index = (int)poll_count;
            poll_fds[poll_count].fd = runtime->text_memos.inotify_fd;
            poll_fds[poll_count].events = POLLIN;
            poll_fds[poll_count].revents = 0;
            poll_count++;
        }
        if (runtime->voice_memos.inotify_fd >= 0) {
            voice_memos_poll_index = (int)poll_count;
            poll_fds[poll_count].fd = runtime->voice_memos.inotify_fd;
            poll_fds[poll_count].events = POLLIN;
            poll_fds[poll_count].revents = 0;
            poll_count++;
        }
        if (video != NULL && poll_count < (sizeof(poll_fds) / sizeof(poll_fds[0]))) {
            int max_video_fds = (int)((sizeof(poll_fds) / sizeof(poll_fds[0])) - poll_count);
            video_poll_index = (int)poll_count;
            video_poll_count = c300x_video_pollfds(video, &poll_fds[poll_count], max_video_fds);
            poll_count += (nfds_t)video_poll_count;
            poll_timeout_ms = min_timeout_ms(
                poll_timeout_ms,
                c300x_video_poll_timeout_ms(video)
            );
        }
        if (system_metrics_watch_active(config, runtime)) {
            poll_timeout_ms = min_timeout_ms(
                poll_timeout_ms,
                timeout_until_ms(now, runtime->system_metrics_next_sample_at)
            );
        }
        poll_timeout_ms = min_timeout_ms(poll_timeout_ms, ui_event_timeout_ms(runtime, now));
        runtime->loop_iterations++;
        runtime->last_poll_timeout_ms = poll_timeout_ms;
        runtime->last_poll_count = (int)poll_count;
        int poll_result = poll(poll_fds, poll_count, poll_timeout_ms);
        if (poll_result < 0) {
            if (errno == EINTR) {
                continue;
            }
            fprintf(stderr, "poll failed: %s\n", strerror(errno));
            break;
        }
        if (poll_result == 0) {
            runtime_set_wake_reason(runtime, "timeout");
        } else {
            runtime->poll_wakeups++;
            runtime_set_wake_reason(runtime, "event");
        }
        for (index = 0; index < listener_count; index++) {
            if ((poll_fds[index].revents & POLLIN) != 0) {
                runtime_set_wake_reason(runtime, listeners[index].kind == LISTENER_UI ? "ui" : "api");
                for (;;) {
                    int client_fd = accept(listeners[index].fd, NULL, NULL);
                    if (client_fd < 0) {
                        if (errno == EINTR) {
                            continue;
                        }
                        if (errno == EAGAIN || errno == EWOULDBLOCK) {
                            break;
                        }
                        break;
                    }
                    runtime->accepted_clients++;
                    handle_client(client_fd, listeners[index].kind, config, runtime);
                }
            }
        }
        if (udp_poll_index >= 0 && (poll_fds[udp_poll_index].revents & POLLIN) != 0) {
            runtime_set_wake_reason(runtime, "udp_event");
            handle_udp_event(udp_fd, config, runtime);
        }
        if (mdns_poll_index >= 0) {
            if ((poll_fds[mdns_poll_index].revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
                runtime_set_wake_reason(runtime, "mdns_error");
                c300x_mdns_close(&mdns);
            } else if ((poll_fds[mdns_poll_index].revents & POLLIN) != 0) {
                runtime_set_wake_reason(runtime, "mdns");
                c300x_mdns_handle_query(&mdns, config);
            }
        }
        if (mqtt_poll_index >= 0) {
            runtime_set_wake_reason(runtime, "mqtt");
            c300x_mqtt_handle_poll(&runtime->mqtt, config, poll_fds[mqtt_poll_index].revents, time(NULL));
            handle_mqtt_commands(config, runtime);
        }
        if (voicemail_poll_index >= 0) {
            if ((poll_fds[voicemail_poll_index].revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
                runtime_set_wake_reason(runtime, "video_messages_error");
                voicemail_close(&runtime->voicemail);
            } else if ((poll_fds[voicemail_poll_index].revents & POLLIN) != 0) {
                runtime_set_wake_reason(runtime, "video_messages");
                handle_voicemail_inotify(config, runtime);
            }
        }
        if (text_memos_poll_index >= 0) {
            if ((poll_fds[text_memos_poll_index].revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
                runtime_set_wake_reason(runtime, "text_memos_error");
                voicemail_close(&runtime->text_memos);
            } else if ((poll_fds[text_memos_poll_index].revents & POLLIN) != 0) {
                runtime_set_wake_reason(runtime, "text_memos");
                handle_memos_inotify(config, runtime, &runtime->text_memos);
            }
        }
        if (voice_memos_poll_index >= 0) {
            if ((poll_fds[voice_memos_poll_index].revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
                runtime_set_wake_reason(runtime, "voice_memos_error");
                voicemail_close(&runtime->voice_memos);
            } else if ((poll_fds[voice_memos_poll_index].revents & POLLIN) != 0) {
                runtime_set_wake_reason(runtime, "voice_memos");
                handle_memos_inotify(config, runtime, &runtime->voice_memos);
            }
        }
        if (video != NULL && video_poll_index >= 0 && video_poll_count > 0) {
            runtime_set_wake_reason(runtime, "video");
            c300x_video_handle_pollfds(video, &poll_fds[video_poll_index], video_poll_count);
        }
        ui_event_expire_wait(runtime, time(NULL));
        c300x_mdns_announce_if_due(&mdns, config, time(NULL));
        c300x_mqtt_tick(&runtime->mqtt, config, time(NULL));
        handle_mqtt_commands(config, runtime);
        if (system_metrics_watch_active(config, runtime)) {
            system_metrics_dispatch_if_due(config, runtime, time(NULL));
        }
    }

cleanup:
    for (nfds_t index = 0; index < listener_count; index++) {
        close(listeners[index].fd);
    }
    if (udp_fd >= 0) {
        close(udp_fd);
    }
    c300x_mdns_close(&mdns);
    if (runtime != NULL) {
        c300x_mqtt_close(&runtime->mqtt);
        voicemail_close(&runtime->voicemail);
        voicemail_close(&runtime->text_memos);
        voicemail_close(&runtime->voice_memos);
        ui_event_close_wait(runtime, 0);
    }
    c300x_video_destroy(video);
    free(runtime);
    return result;
}
