#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#include "c300x_agent.h"

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <sys/stat.h>
#include <unistd.h>

static void set_error(char *error, size_t error_len, const char *message)
{
    if (error_len == 0) {
        return;
    }
    snprintf(error, error_len, "%s", message);
}

static void safe_copy(char *dest, size_t dest_len, const char *value)
{
    if (dest_len == 0) {
        return;
    }
    snprintf(dest, dest_len, "%s", value != NULL ? value : "");
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

static int activation_id_is_valid(const char *value)
{
    size_t len = strlen(value);
    if (len == 0 || len >= C300X_MAX_ACTIVATION_ID_LEN) {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        unsigned char ch = (unsigned char)value[index];
        if (!isalnum(ch) && ch != '_' && ch != '-') {
            return 0;
        }
    }
    return 1;
}

static int activation_type_is_valid(const char *value)
{
    return strcmp(value, "lock") == 0
        || strcmp(value, "light") == 0
        || strcmp(value, "stair_light") == 0
        || strcmp(value, "generic") == 0
        || strcmp(value, "scenario") == 0
        || strcmp(value, "unknown") == 0;
}

static int activation_address_mode_is_valid(const char *value)
{
    return strcmp(value, "manual") == 0 || strcmp(value, "auto") == 0;
}

static int openwebnet_command_is_valid(const char *value)
{
    size_t len = strlen(value);
    if (len == 0) {
        return 1;
    }
    if (len < 3 || len >= C300X_MAX_FRAME_LEN || value[0] != '*') {
        return 0;
    }
    if (value[len - 1] != '#' || value[len - 2] != '#') {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        if (!isdigit((unsigned char)value[index])
            && value[index] != '*'
            && value[index] != '#') {
            return 0;
        }
    }
    return 1;
}

void c300x_default_config(struct c300x_config *config)
{
    memset(config, 0, sizeof(*config));
    safe_copy(config->listen_host, sizeof(config->listen_host), "127.0.0.1");
    safe_copy(config->config_path, sizeof(config->config_path), "config.json");
    config->api_port = 8091;
    config->ui_port = 8090;
    config->allow_lan = 0;
    config->display_bridge_enabled = 0;
    safe_copy(config->device_model, sizeof(config->device_model), "C300X");
    safe_copy(config->device_firmware, sizeof(config->device_firmware), "");
    safe_copy(config->openwebnet_host, sizeof(config->openwebnet_host), "127.0.0.1");
    config->openwebnet_port = 20000;
    config->openwebnet_timeout_ms = 3000;
    safe_copy(
        config->stair_light_default_address,
        sizeof(config->stair_light_default_address),
        "10"
    );
    safe_copy(config->lock_id, sizeof(config->lock_id), "default");
    safe_copy(config->lock_name, sizeof(config->lock_name), "Main door");
    safe_copy(config->lock_address, sizeof(config->lock_address), "20");
    config->lock_release_delay_ms = 2000;
    config->activations_auto_discover = 1;
    config->activation_discovery_root_count = 3;
    safe_copy(
        config->activation_discovery_roots[0],
        sizeof(config->activation_discovery_roots[0]),
        "/home/bticino/cfg/extra/47"
    );
    safe_copy(
        config->activation_discovery_roots[1],
        sizeof(config->activation_discovery_roots[1]),
        "/home/bticino/cfg/extra"
    );
    safe_copy(
        config->activation_discovery_roots[2],
        sizeof(config->activation_discovery_roots[2]),
        "/home/bticino/cfg"
    );
    config->maintenance_reboot_delay_ms = 500;
    config->maintenance_agent_remove_script[0] = '\0';
    config->maintenance_gui_reload_script[0] = '\0';
    config->maintenance_qml_patch_script[0] = '\0';
    safe_copy(
        config->maintenance_firewall_path,
        sizeof(config->maintenance_firewall_path),
        "/etc/network/if-pre-up.d/iptables"
    );
    safe_copy(
        config->maintenance_firewall_backup_path,
        sizeof(config->maintenance_firewall_backup_path),
        "/home/bticino/cfg/extra/c300x-device-file-backups/original/etc/network/if-pre-up.d/iptables"
    );
    safe_copy(
        config->maintenance_ipv6_firewall_path,
        sizeof(config->maintenance_ipv6_firewall_path),
        "/etc/network/if-pre-up.d/iptables6"
    );
    safe_copy(
        config->maintenance_ipv6_firewall_backup_path,
        sizeof(config->maintenance_ipv6_firewall_backup_path),
        "/home/bticino/cfg/extra/c300x-device-file-backups/original/etc/network/if-pre-up.d/iptables6"
    );
    config->maintenance_no_auth_allowed = 0;
    config->mdns_enabled = 1;
    safe_copy(config->mdns_name, sizeof(config->mdns_name), "BTicino C300X");
    config->events_enabled = 1;
    safe_copy(config->events_group, sizeof(config->events_group), "239.255.76.67");
    config->events_port = 7667;
    safe_copy(
        config->subscription_store_path,
        sizeof(config->subscription_store_path),
        "/home/bticino/cfg/extra/c300x-native-agent/subscriptions.json"
    );
    config->callback_timeout_ms = 2500;
    config->mqtt_enabled = 0;
    config->mqtt_host[0] = '\0';
    config->mqtt_port = 1883;
    config->mqtt_username[0] = '\0';
    config->mqtt_password[0] = '\0';
    safe_copy(config->mqtt_client_id, sizeof(config->mqtt_client_id), "c300x-native-agent");
    safe_copy(config->mqtt_command_host, sizeof(config->mqtt_command_host), "127.0.0.1");
    config->mqtt_command_port = 30006;
    safe_copy(config->mqtt_command_topic, sizeof(config->mqtt_command_topic), "Bticino/rx");
    safe_copy(config->mqtt_event_topic, sizeof(config->mqtt_event_topic), "Bticino/tx");
    config->mqtt_json_event_topic[0] = '\0';
    safe_copy(config->mqtt_status_topic, sizeof(config->mqtt_status_topic), "Bticino/start_date");
    safe_copy(config->mqtt_availability_topic, sizeof(config->mqtt_availability_topic), "Bticino/LastWillT");
    config->mqtt_qos = 0;
    config->mqtt_keepalive_seconds = 120;
    config->mqtt_reconnect_initial_seconds = 30;
    config->mqtt_reconnect_max_seconds = 600;
    config->home_assistant_request_timeout_ms = 3000;
    config->api_no_auth = 0;
    config->video_enabled = 0;
    safe_copy(config->video_av_host, sizeof(config->video_av_host), "127.0.0.1");
    config->video_av_port = 30007;
    config->video_av_timeout_ms = 5000;
    config->video_av_high_resolution = 1;
    config->video_rtsp_port = 6554;
    config->video_rtp_port_start = 10000;
    config->video_rtp_port_count = 100;
    config->video_rtsp_keep_alive_ms = 7500;
    safe_copy(config->video_rtsp_path, sizeof(config->video_rtsp_path), "/doorbell");
    safe_copy(config->video_rtsp_video_path, sizeof(config->video_rtsp_video_path), "/doorbell-video");
    safe_copy(config->video_rtsp_recorder_path, sizeof(config->video_rtsp_recorder_path), "/doorbell-recorder");
    safe_copy(config->video_rtsp_username, sizeof(config->video_rtsp_username), "");
    safe_copy(config->video_rtsp_password, sizeof(config->video_rtsp_password), "");
    safe_copy(config->video_sip_from, sizeof(config->video_sip_from), "webrtc");
    safe_copy(config->video_sip_to, sizeof(config->video_sip_to), "c300x");
    safe_copy(config->video_sip_domain, sizeof(config->video_sip_domain), "");
    safe_copy(config->video_sip_devaddr, sizeof(config->video_sip_devaddr), "20");
    safe_copy(config->video_sip_local_ip, sizeof(config->video_sip_local_ip), "127.0.0.1");
    config->video_sip_local_port = 5060;
    config->video_sip_use_tcp = 1;
    config->video_sip_debug = 0;
    config->answering_machine_messages_enabled = 1;
    safe_copy(
        config->answering_machine_messages_root,
        sizeof(config->answering_machine_messages_root),
        "/home/bticino/cfg/extra/47/messages"
    );
    config->answering_machine_messages_watch = 1;
    config->answering_machine_messages_max = 64;
    config->system_metrics_enabled = 1;
    config->system_metrics_watch = 1;
    config->system_metrics_sample_interval_seconds = 30;
    config->system_metrics_heartbeat_seconds = 600;
    config->system_metrics_change_percent = 5;
    config->memos_enabled = 1;
    safe_copy(
        config->memos_text_root,
        sizeof(config->memos_text_root),
        "/home/bticino/cfg/extra/47/memos_text"
    );
    safe_copy(
        config->memos_voice_root,
        sizeof(config->memos_voice_root),
        "/home/bticino/cfg/extra/47/memos_voice"
    );
    config->memos_watch = 1;
    config->memos_max = 64;
}

static char *read_file(const char *path, char *error, size_t error_len)
{
    FILE *file = fopen(path, "rb");
    long size;
    char *buffer;

    if (file == NULL) {
        snprintf(error, error_len, "cannot open config: %s", strerror(errno));
        return NULL;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        set_error(error, error_len, "cannot seek config");
        fclose(file);
        return NULL;
    }
    size = ftell(file);
    if (size < 0 || size > 1024 * 1024) {
        set_error(error, error_len, "invalid config size");
        fclose(file);
        return NULL;
    }
    if (fseek(file, 0, SEEK_SET) != 0) {
        set_error(error, error_len, "cannot rewind config");
        fclose(file);
        return NULL;
    }
    buffer = calloc((size_t)size + 1, 1);
    if (buffer == NULL) {
        set_error(error, error_len, "out of memory");
        fclose(file);
        return NULL;
    }
    if (fread(buffer, 1, (size_t)size, file) != (size_t)size) {
        set_error(error, error_len, "cannot read config");
        free(buffer);
        fclose(file);
        return NULL;
    }
    fclose(file);
    return buffer;
}

static const char *skip_ws(const char *ptr, const char *end)
{
    while (ptr < end && isspace((unsigned char)*ptr)) {
        ptr++;
    }
    return ptr;
}

static const char *skip_json_string(const char *ptr, const char *end)
{
    if (ptr >= end || *ptr != '"') {
        return NULL;
    }
    ptr++;
    while (ptr < end) {
        if (*ptr == '\\') {
            ptr += ptr + 1 < end ? 2 : 1;
            continue;
        }
        if (*ptr == '"') {
            return ptr + 1;
        }
        ptr++;
    }
    return NULL;
}

static const char *skip_json_value(const char *ptr, const char *end)
{
    int object_depth = 0;
    int array_depth = 0;

    ptr = skip_ws(ptr, end);
    if (ptr >= end) {
        return NULL;
    }
    if (*ptr == '"') {
        return skip_json_string(ptr, end);
    }
    while (ptr < end) {
        if (*ptr == '"') {
            ptr = skip_json_string(ptr, end);
            if (ptr == NULL) {
                return NULL;
            }
            continue;
        }
        if (*ptr == '{') {
            object_depth++;
        } else if (*ptr == '}') {
            if (object_depth == 0) {
                break;
            }
            object_depth--;
            if (object_depth == 0 && array_depth == 0) {
                return ptr + 1;
            }
        } else if (*ptr == '[') {
            array_depth++;
        } else if (*ptr == ']') {
            if (array_depth == 0) {
                break;
            }
            array_depth--;
            if (object_depth == 0 && array_depth == 0) {
                return ptr + 1;
            }
        } else if (object_depth == 0 && array_depth == 0 && (*ptr == ',' || *ptr == '}')) {
            return ptr;
        }
        ptr++;
    }
    return ptr;
}

static int key_equals(const char *start, const char *end, const char *key)
{
    size_t key_len = strlen(key);
    return (size_t)(end - start) == key_len && strncmp(start, key, key_len) == 0;
}

static int find_member(
    const char *object_start,
    const char *object_end,
    const char *key,
    const char **value
)
{
    const char *ptr = skip_ws(object_start, object_end);

    if (ptr >= object_end || *ptr != '{') {
        return 0;
    }
    ptr++;
    while (ptr < object_end) {
        const char *key_start;
        const char *key_end;
        const char *after_key;

        ptr = skip_ws(ptr, object_end);
        if (ptr >= object_end || *ptr == '}') {
            return 0;
        }
        if (*ptr != '"') {
            return 0;
        }
        key_start = ptr + 1;
        after_key = skip_json_string(ptr, object_end);
        if (after_key == NULL) {
            return 0;
        }
        key_end = after_key - 1;
        ptr = skip_ws(after_key, object_end);
        if (ptr >= object_end || *ptr != ':') {
            return 0;
        }
        ptr = skip_ws(ptr + 1, object_end);
        if (key_equals(key_start, key_end, key)) {
            *value = ptr;
            return 1;
        }
        ptr = skip_json_value(ptr, object_end);
        if (ptr == NULL) {
            return 0;
        }
        ptr = skip_ws(ptr, object_end);
        if (ptr < object_end && *ptr == ',') {
            ptr++;
        }
    }
    return 0;
}

static int object_bounds(const char *value, const char *document_end, const char **end)
{
    const char *after;

    value = skip_ws(value, document_end);
    if (value >= document_end || *value != '{') {
        return 0;
    }
    after = skip_json_value(value, document_end);
    if (after == NULL) {
        return 0;
    }
    *end = after;
    return 1;
}

static int array_bounds(const char *value, const char *document_end, const char **end)
{
    const char *after;

    value = skip_ws(value, document_end);
    if (value >= document_end || *value != '[') {
        return 0;
    }
    after = skip_json_value(value, document_end);
    if (after == NULL) {
        return 0;
    }
    *end = after;
    return 1;
}

static int nested_member(
    const char *document,
    const char *document_end,
    const char *object_key,
    const char *member_key,
    const char **value
)
{
    const char *object_value;
    const char *object_end;

    if (!find_member(document, document_end, object_key, &object_value)) {
        return 0;
    }
    if (!object_bounds(object_value, document_end, &object_end)) {
        return 0;
    }
    return find_member(object_value, object_end, member_key, value);
}

static int nested_member3(
    const char *document,
    const char *document_end,
    const char *first_key,
    const char *second_key,
    const char *member_key,
    const char **value
)
{
    const char *object_value;
    const char *object_end;

    if (!nested_member(document, document_end, first_key, second_key, &object_value)) {
        return 0;
    }
    if (!object_bounds(object_value, document_end, &object_end)) {
        return 0;
    }
    return find_member(object_value, object_end, member_key, value);
}

static int nested_member4(
    const char *document,
    const char *document_end,
    const char *first_key,
    const char *second_key,
    const char *third_key,
    const char *member_key,
    const char **value
)
{
    const char *object_value;
    const char *object_end;

    if (!nested_member3(
        document,
        document_end,
        first_key,
        second_key,
        third_key,
        &object_value
    )) {
        return 0;
    }
    if (!object_bounds(object_value, document_end, &object_end)) {
        return 0;
    }
    return find_member(object_value, object_end, member_key, value);
}

static int string_value(const char *value, const char *document_end, char *out, size_t out_len)
{
    const char *ptr;
    size_t written = 0;

    value = skip_ws(value, document_end);
    if (value >= document_end || *value != '"') {
        return 0;
    }
    ptr = value + 1;
    while (ptr < document_end && *ptr != '"') {
        char ch = *ptr++;
        if (ch == '\\' && ptr < document_end) {
            ch = *ptr++;
        }
        if (written + 1 < out_len) {
            out[written++] = ch;
        }
    }
    if (ptr >= document_end || *ptr != '"') {
        return 0;
    }
    if (out_len > 0) {
        out[written] = '\0';
    }
    return 1;
}

static int uint16_value(const char *value, const char *document_end, uint16_t *out)
{
    char *parse_end = NULL;
    long parsed;

    value = skip_ws(value, document_end);
    parsed = strtol(value, &parse_end, 10);
    if (parse_end == value || parsed <= 0 || parsed > 65535) {
        return 0;
    }
    *out = (uint16_t)parsed;
    return 1;
}

static int int_value(const char *value, const char *document_end, int *out)
{
    char *parse_end = NULL;
    long parsed;

    value = skip_ws(value, document_end);
    parsed = strtol(value, &parse_end, 10);
    if (parse_end == value || parsed <= 0 || parsed > 60000) {
        return 0;
    }
    *out = (int)parsed;
    return 1;
}

static int int_range_value(
    const char *value,
    const char *document_end,
    int minimum,
    int maximum,
    int *out
)
{
    char *parse_end = NULL;
    long parsed;

    value = skip_ws(value, document_end);
    parsed = strtol(value, &parse_end, 10);
    if (parse_end == value || parsed < minimum || parsed > maximum) {
        return 0;
    }
    *out = (int)parsed;
    return 1;
}

static int bool_value(const char *value, const char *document_end, int *out)
{
    value = skip_ws(value, document_end);
    if ((size_t)(document_end - value) >= 4 && strncmp(value, "true", 4) == 0) {
        *out = 1;
        return 1;
    }
    if ((size_t)(document_end - value) >= 5 && strncmp(value, "false", 5) == 0) {
        *out = 0;
        return 1;
    }
    return 0;
}

static const char *next_array_value(
    const char *ptr,
    const char *array_end,
    const char **value,
    const char **value_end
)
{
    const char *after;

    ptr = skip_ws(ptr, array_end);
    if (ptr >= array_end || *ptr == ']') {
        return NULL;
    }
    after = skip_json_value(ptr, array_end);
    if (after == NULL || after <= ptr) {
        return NULL;
    }
    *value = ptr;
    *value_end = after;
    after = skip_ws(after, array_end);
    if (after < array_end && *after == ',') {
        after++;
    } else if (after < array_end && *after != ']') {
        return NULL;
    }
    return after;
}

static int parse_activation_item(
    const char *item,
    const char *document_end,
    struct c300x_activation *activation,
    char *error,
    size_t error_len
)
{
    const char *item_end;
    const char *value;
    char activation_id[C300X_MAX_ACTIVATION_ID_LEN + 1];

    memset(activation, 0, sizeof(*activation));
    safe_copy(activation->type, sizeof(activation->type), "unknown");
    safe_copy(activation->address_mode, sizeof(activation->address_mode), "manual");
    if (!object_bounds(item, document_end, &item_end)) {
        set_error(error, error_len, "activations.items entries must be objects");
        return 0;
    }
    if (!find_member(item, item_end, "id", &value)
        || !string_value(value, document_end, activation_id, sizeof(activation_id))
        || !activation_id_is_valid(activation_id)) {
        set_error(error, error_len, "activations item id must be a safe string");
        return 0;
    }
    safe_copy(activation->id, sizeof(activation->id), activation_id);
    if (!find_member(item, item_end, "name", &value)
        || !string_value(value, document_end, activation->name, sizeof(activation->name))
        || activation->name[0] == '\0') {
        set_error(error, error_len, "activations item name must be a string");
        return 0;
    }
    if (find_member(item, item_end, "type", &value)) {
        if (!string_value(value, document_end, activation->type, sizeof(activation->type))
            || !activation_type_is_valid(activation->type)) {
            set_error(error, error_len, "activations item type is invalid");
            return 0;
        }
    }
    if (find_member(item, item_end, "addressMode", &value)) {
        if (!string_value(value, document_end, activation->address_mode, sizeof(activation->address_mode))
            || !activation_address_mode_is_valid(activation->address_mode)) {
            set_error(error, error_len, "activations item addressMode is invalid");
            return 0;
        }
    }
    if (find_member(item, item_end, "address", &value)) {
        if (!string_value(value, document_end, activation->address, sizeof(activation->address))
            || !address_is_valid(activation->address)) {
            set_error(error, error_len, "activations item address is invalid");
            return 0;
        }
    }
    if (find_member(item, item_end, "pressCommand", &value)) {
        if (!string_value(value, document_end, activation->press_command, sizeof(activation->press_command))
            || !openwebnet_command_is_valid(activation->press_command)) {
            set_error(error, error_len, "activations item pressCommand is invalid");
            return 0;
        }
    }
    if (find_member(item, item_end, "releaseCommand", &value)) {
        if (!string_value(value, document_end, activation->release_command, sizeof(activation->release_command))
            || !openwebnet_command_is_valid(activation->release_command)) {
            set_error(error, error_len, "activations item releaseCommand is invalid");
            return 0;
        }
    }
    if (find_member(item, item_end, "holdMs", &value)
        && !int_range_value(value, document_end, 0, 60000, &activation->hold_ms)) {
        set_error(error, error_len, "activations item holdMs is invalid");
        return 0;
    }
    return 1;
}

static int parse_activation_discovery_roots(
    const char *value,
    const char *document_end,
    struct c300x_config *config,
    char *error,
    size_t error_len
)
{
    const char *array_end;
    const char *ptr;
    const char *item;
    const char *item_end;

    if (!array_bounds(value, document_end, &array_end)) {
        set_error(error, error_len, "activations.discoveryRoots must be an array");
        return 0;
    }
    config->activation_discovery_root_count = 0;
    ptr = skip_ws(value, array_end);
    if (ptr < array_end && *ptr == '[') {
        ptr++;
    }
    while ((ptr = next_array_value(ptr, array_end, &item, &item_end)) != NULL) {
        char root[C300X_MAX_PATH_LEN];

        (void)item_end;
        if (config->activation_discovery_root_count >= C300X_MAX_ACTIVATION_DISCOVERY_ROOTS) {
            set_error(error, error_len, "too many activation discovery roots configured");
            return 0;
        }
        if (!string_value(item, document_end, root, sizeof(root)) || root[0] == '\0') {
            set_error(error, error_len, "activations.discoveryRoots entries must be strings");
            return 0;
        }
        safe_copy(
            config->activation_discovery_roots[config->activation_discovery_root_count],
            sizeof(config->activation_discovery_roots[config->activation_discovery_root_count]),
            root
        );
        config->activation_discovery_root_count++;
    }
    return 1;
}

int c300x_load_config(
    const char *config_path,
    struct c300x_config *config,
    char *error,
    size_t error_len
)
{
    const char *env_token;
    char *document = NULL;
    const char *document_end;
    const char *value;

    c300x_default_config(config);
    env_token = getenv("C300X_AGENT_TOKEN");
    if (config_path != NULL && config_path[0] != '\0') {
        safe_copy(config->config_path, sizeof(config->config_path), config_path);
    }

    if (config_path == NULL || config_path[0] == '\0') {
        if (env_token != NULL && env_token[0] != '\0') {
            safe_copy(config->api_token, sizeof(config->api_token), env_token);
            config->api_token_from_env = 1;
        }
        return 1;
    }

    document = read_file(config_path, error, error_len);
    if (document == NULL) {
        return 0;
    }
    document_end = document + strlen(document);

    if (nested_member(document, document_end, "listen", "host", &value)) {
        if (!string_value(value, document_end, config->listen_host, sizeof(config->listen_host))) {
            set_error(error, error_len, "listen.host must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "listen", "apiPort", &value)) {
        if (!uint16_value(value, document_end, &config->api_port)) {
            set_error(error, error_len, "listen.apiPort must be a valid port");
            free(document);
            return 0;
        }
    } else if (nested_member(document, document_end, "listen", "port", &value)) {
        if (!uint16_value(value, document_end, &config->api_port)) {
            set_error(error, error_len, "listen.port must be a valid port");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "listen", "uiPort", &value)) {
        if (!uint16_value(value, document_end, &config->ui_port)) {
            set_error(error, error_len, "listen.uiPort must be a valid port");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "listen", "allowLan", &value)) {
        if (!bool_value(value, document_end, &config->allow_lan)) {
            set_error(error, error_len, "listen.allowLan must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "api", "token", &value)) {
        if (!string_value(value, document_end, config->api_token, sizeof(config->api_token))) {
            set_error(error, error_len, "api.token must be a string");
            free(document);
            return 0;
        }
        safe_copy(config->api_file_token, sizeof(config->api_file_token), config->api_token);
    }
    if (nested_member(document, document_end, "api", "noAuth", &value)) {
        if (!bool_value(value, document_end, &config->api_no_auth)) {
            set_error(error, error_len, "api.noAuth must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "device", "model", &value)) {
        if (!string_value(
            value,
            document_end,
            config->device_model,
            sizeof(config->device_model)
        )) {
            set_error(error, error_len, "device.model must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "device", "firmware", &value)) {
        if (!string_value(
            value,
            document_end,
            config->device_firmware,
            sizeof(config->device_firmware)
        )) {
            set_error(error, error_len, "device.firmware must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "device", "stairLightDefaultAddress", &value)) {
        if (!string_value(
            value,
            document_end,
            config->stair_light_default_address,
            sizeof(config->stair_light_default_address)
        )) {
            set_error(error, error_len, "device.stairLightDefaultAddress must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "openwebnet", "host", &value)) {
        if (!string_value(
            value,
            document_end,
            config->openwebnet_host,
            sizeof(config->openwebnet_host)
        )) {
            set_error(error, error_len, "openwebnet.host must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "openwebnet", "port", &value)) {
        if (!uint16_value(value, document_end, &config->openwebnet_port)) {
            set_error(error, error_len, "openwebnet.port must be a valid port");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "openwebnet", "timeoutMs", &value)) {
        if (!int_value(value, document_end, &config->openwebnet_timeout_ms)) {
            set_error(error, error_len, "openwebnet.timeoutMs must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "activations", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->activations_enabled)) {
            set_error(error, error_len, "activations.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "activations", "autoDiscover", &value)) {
        if (!bool_value(value, document_end, &config->activations_auto_discover)) {
            set_error(error, error_len, "activations.autoDiscover must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "activations", "discoveryRoots", &value)) {
        if (!parse_activation_discovery_roots(value, document_end, config, error, error_len)) {
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "activations", "items", &value)) {
        const char *array_end;
        const char *ptr;
        const char *item;
        const char *item_end;

        if (!array_bounds(value, document_end, &array_end)) {
            set_error(error, error_len, "activations.items must be an array");
            free(document);
            return 0;
        }
        config->activations_count = 0;
        ptr = skip_ws(value, array_end);
        if (ptr < array_end && *ptr == '[') {
            ptr++;
        }
        while ((ptr = next_array_value(ptr, array_end, &item, &item_end)) != NULL) {
            (void)item_end;
            if (config->activations_count >= C300X_MAX_ACTIVATIONS) {
                set_error(error, error_len, "too many activations configured");
                free(document);
                return 0;
            }
            if (!parse_activation_item(
                item,
                document_end,
                &config->activations[config->activations_count],
                error,
                error_len
            )) {
                free(document);
                return 0;
            }
            config->activations_count++;
        }
    }
    if (nested_member(document, document_end, "locks", "releaseDelayMs", &value)) {
        if (!int_value(value, document_end, &config->lock_release_delay_ms)) {
            set_error(error, error_len, "locks.releaseDelayMs must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "maintenance", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->maintenance_enabled)) {
            set_error(error, error_len, "maintenance.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "maintenance", "adminToken", &value)) {
        if (!string_value(
            value,
            document_end,
            config->maintenance_admin_token,
            sizeof(config->maintenance_admin_token)
        )) {
            set_error(error, error_len, "maintenance.adminToken must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "sshStart", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->maintenance_ssh_start_enabled)) {
            set_error(error, error_len, "maintenance.sshStart.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "reboot", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->maintenance_reboot_enabled)) {
            set_error(error, error_len, "maintenance.reboot.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "reboot", "delayMs", &value)) {
        if (!int_value(value, document_end, &config->maintenance_reboot_delay_ms)) {
            set_error(error, error_len, "maintenance.reboot.delayMs must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "agentRemove", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->maintenance_agent_remove_enabled)) {
            set_error(error, error_len, "maintenance.agentRemove.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "agentRemove", "script", &value)) {
        if (!string_value(
            value,
            document_end,
            config->maintenance_agent_remove_script,
            sizeof(config->maintenance_agent_remove_script)
        )) {
            set_error(error, error_len, "maintenance.agentRemove.script must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "guiReload", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->maintenance_gui_reload_enabled)) {
            set_error(error, error_len, "maintenance.guiReload.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "guiReload", "script", &value)) {
        if (!string_value(
            value,
            document_end,
            config->maintenance_gui_reload_script,
            sizeof(config->maintenance_gui_reload_script)
        )) {
            set_error(error, error_len, "maintenance.guiReload.script must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "qmlPatch", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->maintenance_qml_patch_enabled)) {
            set_error(error, error_len, "maintenance.qmlPatch.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "qmlPatch", "script", &value)) {
        if (!string_value(
            value,
            document_end,
            config->maintenance_qml_patch_script,
            sizeof(config->maintenance_qml_patch_script)
        )) {
            set_error(error, error_len, "maintenance.qmlPatch.script must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "firewall", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->maintenance_firewall_enabled)) {
            set_error(error, error_len, "maintenance.firewall.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "firewall", "path", &value)) {
        if (!string_value(
            value,
            document_end,
            config->maintenance_firewall_path,
            sizeof(config->maintenance_firewall_path)
        )) {
            set_error(error, error_len, "maintenance.firewall.path must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "firewall", "backupPath", &value)) {
        if (!string_value(
            value,
            document_end,
            config->maintenance_firewall_backup_path,
            sizeof(config->maintenance_firewall_backup_path)
        )) {
            set_error(error, error_len, "maintenance.firewall.backupPath must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "ipv6Firewall", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->maintenance_ipv6_firewall_enabled)) {
            set_error(error, error_len, "maintenance.ipv6Firewall.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "ipv6Firewall", "path", &value)) {
        if (!string_value(
            value,
            document_end,
            config->maintenance_ipv6_firewall_path,
            sizeof(config->maintenance_ipv6_firewall_path)
        )) {
            set_error(error, error_len, "maintenance.ipv6Firewall.path must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "maintenance", "ipv6Firewall", "backupPath", &value)) {
        if (!string_value(
            value,
            document_end,
            config->maintenance_ipv6_firewall_backup_path,
            sizeof(config->maintenance_ipv6_firewall_backup_path)
        )) {
            set_error(error, error_len, "maintenance.ipv6Firewall.backupPath must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "maintenance", "allowNoAuth", &value)) {
        if (!bool_value(value, document_end, &config->maintenance_no_auth_allowed)) {
            set_error(error, error_len, "maintenance.allowNoAuth must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mdns", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->mdns_enabled)) {
            set_error(error, error_len, "mdns.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mdns", "name", &value)) {
        if (!string_value(value, document_end, config->mdns_name, sizeof(config->mdns_name))) {
            set_error(error, error_len, "mdns.name must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "events", "subscriptionStorePath", &value)) {
        if (!string_value(
            value,
            document_end,
            config->subscription_store_path,
            sizeof(config->subscription_store_path)
        )) {
            set_error(error, error_len, "events.subscriptionStorePath must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "events", "callbackTimeoutMs", &value)) {
        if (!int_value(value, document_end, &config->callback_timeout_ms)) {
            set_error(error, error_len, "events.callbackTimeoutMs must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "events", "udp", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->events_enabled)) {
            set_error(error, error_len, "events.udp.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "events", "udp", "group", &value)) {
        if (!string_value(value, document_end, config->events_group, sizeof(config->events_group))) {
            set_error(error, error_len, "events.udp.group must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "events", "udp", "port", &value)) {
        if (!uint16_value(value, document_end, &config->events_port)) {
            set_error(error, error_len, "events.udp.port must be a valid port");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->mqtt_enabled)) {
            set_error(error, error_len, "mqtt.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "host", &value)) {
        if (!string_value(value, document_end, config->mqtt_host, sizeof(config->mqtt_host))) {
            set_error(error, error_len, "mqtt.host must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "port", &value)) {
        if (!uint16_value(value, document_end, &config->mqtt_port)) {
            set_error(error, error_len, "mqtt.port must be a valid port");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "username", &value)) {
        if (!string_value(value, document_end, config->mqtt_username, sizeof(config->mqtt_username))) {
            set_error(error, error_len, "mqtt.username must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "password", &value)) {
        if (!string_value(value, document_end, config->mqtt_password, sizeof(config->mqtt_password))) {
            set_error(error, error_len, "mqtt.password must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "clientId", &value)) {
        if (!string_value(value, document_end, config->mqtt_client_id, sizeof(config->mqtt_client_id))) {
            set_error(error, error_len, "mqtt.clientId must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "commandHost", &value)) {
        if (!string_value(value, document_end, config->mqtt_command_host, sizeof(config->mqtt_command_host))) {
            set_error(error, error_len, "mqtt.commandHost must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "commandPort", &value)) {
        if (!uint16_value(value, document_end, &config->mqtt_command_port)) {
            set_error(error, error_len, "mqtt.commandPort must be a valid port");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "mqtt", "topics", "command", &value)) {
        if (!string_value(value, document_end, config->mqtt_command_topic, sizeof(config->mqtt_command_topic))) {
            set_error(error, error_len, "mqtt.topics.command must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "mqtt", "topics", "event", &value)) {
        if (!string_value(value, document_end, config->mqtt_event_topic, sizeof(config->mqtt_event_topic))) {
            set_error(error, error_len, "mqtt.topics.event must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "mqtt", "topics", "jsonEvent", &value)) {
        if (!string_value(value, document_end, config->mqtt_json_event_topic, sizeof(config->mqtt_json_event_topic))) {
            set_error(error, error_len, "mqtt.topics.jsonEvent must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "mqtt", "topics", "status", &value)) {
        if (!string_value(value, document_end, config->mqtt_status_topic, sizeof(config->mqtt_status_topic))) {
            set_error(error, error_len, "mqtt.topics.status must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "mqtt", "topics", "availability", &value)) {
        if (!string_value(value, document_end, config->mqtt_availability_topic, sizeof(config->mqtt_availability_topic))) {
            set_error(error, error_len, "mqtt.topics.availability must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "qos", &value)) {
        if (!int_range_value(value, document_end, 0, 0, &config->mqtt_qos)) {
            set_error(error, error_len, "mqtt.qos must be 0");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "keepaliveSeconds", &value)) {
        if (!int_value(value, document_end, &config->mqtt_keepalive_seconds)) {
            set_error(error, error_len, "mqtt.keepaliveSeconds must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "reconnectInitialSeconds", &value)) {
        if (!int_value(value, document_end, &config->mqtt_reconnect_initial_seconds)) {
            set_error(error, error_len, "mqtt.reconnectInitialSeconds must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "mqtt", "reconnectMaxSeconds", &value)) {
        if (!int_value(value, document_end, &config->mqtt_reconnect_max_seconds)) {
            set_error(error, error_len, "mqtt.reconnectMaxSeconds must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "answeringMachine", "messages", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->answering_machine_messages_enabled)) {
            set_error(error, error_len, "answeringMachine.messages.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "answeringMachine", "messages", "root", &value)) {
        if (!string_value(
            value,
            document_end,
            config->answering_machine_messages_root,
            sizeof(config->answering_machine_messages_root)
        )) {
            set_error(error, error_len, "answeringMachine.messages.root must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "answeringMachine", "messages", "watch", &value)) {
        if (!bool_value(value, document_end, &config->answering_machine_messages_watch)) {
            set_error(error, error_len, "answeringMachine.messages.watch must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "answeringMachine", "messages", "maxMessages", &value)) {
        if (!int_value(value, document_end, &config->answering_machine_messages_max)) {
            set_error(error, error_len, "answeringMachine.messages.maxMessages must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "systemMetrics", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->system_metrics_enabled)) {
            set_error(error, error_len, "systemMetrics.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "systemMetrics", "watch", &value)) {
        if (!bool_value(value, document_end, &config->system_metrics_watch)) {
            set_error(error, error_len, "systemMetrics.watch must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "systemMetrics", "sampleIntervalSeconds", &value)) {
        if (!int_value(value, document_end, &config->system_metrics_sample_interval_seconds)) {
            set_error(error, error_len, "systemMetrics.sampleIntervalSeconds must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "systemMetrics", "heartbeatSeconds", &value)) {
        if (!int_value(value, document_end, &config->system_metrics_heartbeat_seconds)) {
            set_error(error, error_len, "systemMetrics.heartbeatSeconds must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "systemMetrics", "changePercent", &value)) {
        if (!int_value(value, document_end, &config->system_metrics_change_percent)) {
            set_error(error, error_len, "systemMetrics.changePercent must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "memos", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->memos_enabled)) {
            set_error(error, error_len, "memos.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "memos", "textRoot", &value)) {
        if (!string_value(value, document_end, config->memos_text_root, sizeof(config->memos_text_root))) {
            set_error(error, error_len, "memos.textRoot must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "memos", "voiceRoot", &value)) {
        if (!string_value(value, document_end, config->memos_voice_root, sizeof(config->memos_voice_root))) {
            set_error(error, error_len, "memos.voiceRoot must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "memos", "watch", &value)) {
        if (!bool_value(value, document_end, &config->memos_watch)) {
            set_error(error, error_len, "memos.watch must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "memos", "maxMemos", &value)) {
        if (!int_value(value, document_end, &config->memos_max)) {
            set_error(error, error_len, "memos.maxMemos must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member4(document, document_end, "locks", "items", "default", "name", &value)) {
        if (!string_value(value, document_end, config->lock_name, sizeof(config->lock_name))) {
            set_error(error, error_len, "locks.items.default.name must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member4(document, document_end, "locks", "items", "default", "address", &value)) {
        if (!string_value(
            value,
            document_end,
            config->lock_address,
            sizeof(config->lock_address)
        )) {
            set_error(error, error_len, "locks.items.default.address must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "displayBridge", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->display_bridge_enabled)) {
            set_error(error, error_len, "displayBridge.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "displayBridge", "homeAssistant", "webhookUrl", &value)) {
        if (!string_value(value, document_end, config->home_assistant_webhook_url, sizeof(config->home_assistant_webhook_url))) {
            set_error(error, error_len, "displayBridge.homeAssistant.webhookUrl must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "displayBridge", "homeAssistant", "sharedSecret", &value)) {
        if (!string_value(value, document_end, config->home_assistant_shared_secret, sizeof(config->home_assistant_shared_secret))) {
            set_error(error, error_len, "displayBridge.homeAssistant.sharedSecret must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "displayBridge", "homeAssistant", "requestTimeoutMs", &value)) {
        if (!int_value(value, document_end, &config->home_assistant_request_timeout_ms)) {
            set_error(error, error_len, "displayBridge.homeAssistant.requestTimeoutMs must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member(document, document_end, "video", "enabled", &value)) {
        if (!bool_value(value, document_end, &config->video_enabled)) {
            set_error(error, error_len, "video.enabled must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "av", "host", &value)) {
        if (!string_value(value, document_end, config->video_av_host, sizeof(config->video_av_host))) {
            set_error(error, error_len, "video.av.host must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "av", "port", &value)) {
        if (!uint16_value(value, document_end, &config->video_av_port)) {
            set_error(error, error_len, "video.av.port must be a valid port");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "av", "timeoutMs", &value)) {
        if (!int_value(value, document_end, &config->video_av_timeout_ms)) {
            set_error(error, error_len, "video.av.timeoutMs must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "av", "highResolution", &value)) {
        if (!bool_value(value, document_end, &config->video_av_high_resolution)) {
            set_error(error, error_len, "video.av.highResolution must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "rtsp", "port", &value)) {
        if (!uint16_value(value, document_end, &config->video_rtsp_port)) {
            set_error(error, error_len, "video.rtsp.port must be a valid port");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "rtsp", "rtpPortStart", &value)) {
        if (!uint16_value(value, document_end, &config->video_rtp_port_start)) {
            set_error(error, error_len, "video.rtsp.rtpPortStart must be a valid port");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "rtsp", "rtpPortCount", &value)) {
        if (!int_value(value, document_end, &config->video_rtp_port_count)) {
            set_error(error, error_len, "video.rtsp.rtpPortCount must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "rtsp", "keepAliveMs", &value)) {
        if (!int_value(value, document_end, &config->video_rtsp_keep_alive_ms)) {
            set_error(error, error_len, "video.rtsp.keepAliveMs must be positive");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "rtsp", "path", &value)) {
        if (!string_value(value, document_end, config->video_rtsp_path, sizeof(config->video_rtsp_path))) {
            set_error(error, error_len, "video.rtsp.path must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "rtsp", "videoPath", &value)) {
        if (!string_value(
            value,
            document_end,
            config->video_rtsp_video_path,
            sizeof(config->video_rtsp_video_path)
        )) {
            set_error(error, error_len, "video.rtsp.videoPath must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "rtsp", "recorderPath", &value)) {
        if (!string_value(
            value,
            document_end,
            config->video_rtsp_recorder_path,
            sizeof(config->video_rtsp_recorder_path)
        )) {
            set_error(error, error_len, "video.rtsp.recorderPath must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "rtsp", "username", &value)) {
        if (!string_value(value, document_end, config->video_rtsp_username, sizeof(config->video_rtsp_username))) {
            set_error(error, error_len, "video.rtsp.username must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "rtsp", "password", &value)) {
        if (!string_value(value, document_end, config->video_rtsp_password, sizeof(config->video_rtsp_password))) {
            set_error(error, error_len, "video.rtsp.password must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "sip", "from", &value)) {
        if (!string_value(value, document_end, config->video_sip_from, sizeof(config->video_sip_from))) {
            set_error(error, error_len, "video.sip.from must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "sip", "to", &value)) {
        if (!string_value(value, document_end, config->video_sip_to, sizeof(config->video_sip_to))) {
            set_error(error, error_len, "video.sip.to must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "sip", "domain", &value)) {
        if (!string_value(value, document_end, config->video_sip_domain, sizeof(config->video_sip_domain))) {
            set_error(error, error_len, "video.sip.domain must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "sip", "devaddr", &value)) {
        if (!string_value(value, document_end, config->video_sip_devaddr, sizeof(config->video_sip_devaddr))) {
            set_error(error, error_len, "video.sip.devaddr must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "sip", "localIp", &value)) {
        if (!string_value(value, document_end, config->video_sip_local_ip, sizeof(config->video_sip_local_ip))) {
            set_error(error, error_len, "video.sip.localIp must be a string");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "sip", "localPort", &value)) {
        if (!uint16_value(value, document_end, &config->video_sip_local_port)) {
            set_error(error, error_len, "video.sip.localPort must be a valid port");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "sip", "useTcp", &value)) {
        if (!bool_value(value, document_end, &config->video_sip_use_tcp)) {
            set_error(error, error_len, "video.sip.useTcp must be a boolean");
            free(document);
            return 0;
        }
    }
    if (nested_member3(document, document_end, "video", "sip", "debug", &value)) {
        if (!bool_value(value, document_end, &config->video_sip_debug)) {
            set_error(error, error_len, "video.sip.debug must be a boolean");
            free(document);
            return 0;
        }
    }
    free(document);
    if (env_token != NULL && env_token[0] != '\0') {
        safe_copy(config->api_token, sizeof(config->api_token), env_token);
        config->api_token_from_env = 1;
    }

    if (strcmp(config->listen_host, "127.0.0.1") != 0 && !config->allow_lan) {
        set_error(error, error_len, "LAN binding requires listen.allowLan=true");
        return 0;
    }
    if (!address_is_valid(config->stair_light_default_address)) {
        set_error(error, error_len, "invalid default stair-light address");
        return 0;
    }
    if (!address_is_valid(config->lock_address)) {
        set_error(error, error_len, "invalid default lock address");
        return 0;
    }
    if (config->video_rtp_port_count < 4) {
        set_error(error, error_len, "video.rtsp.rtpPortCount must be >= 4");
        return 0;
    }
    if (!config->api_no_auth && config->api_token[0] == '\0') {
        set_error(error, error_len, "api.token must be configured when api.noAuth=false");
        return 0;
    }
    if (
        config->maintenance_enabled
        && (
            config->maintenance_ssh_start_enabled
            || config->maintenance_reboot_enabled
            || config->maintenance_agent_remove_enabled
            || config->maintenance_gui_reload_enabled
            || config->maintenance_qml_patch_enabled
            || config->maintenance_firewall_enabled
            || config->maintenance_ipv6_firewall_enabled
        )
        && config->maintenance_admin_token[0] == '\0'
        && !(config->api_no_auth && config->maintenance_no_auth_allowed)
    ) {
        set_error(error, error_len, "maintenance.adminToken must be set when maintenance actions are enabled");
        return 0;
    }
    if (config->maintenance_qml_patch_enabled && config->maintenance_qml_patch_script[0] == '\0') {
        set_error(error, error_len, "maintenance.qmlPatch.script must be set when enabled");
        return 0;
    }
    if (config->maintenance_agent_remove_enabled && config->maintenance_agent_remove_script[0] == '\0') {
        set_error(error, error_len, "maintenance.agentRemove.script must be set when enabled");
        return 0;
    }
    if (config->maintenance_gui_reload_enabled && config->maintenance_gui_reload_script[0] == '\0') {
        set_error(error, error_len, "maintenance.guiReload.script must be set when enabled");
        return 0;
    }
    if (config->maintenance_firewall_enabled) {
        if (
            config->maintenance_firewall_path[0] == '\0'
            || config->maintenance_firewall_backup_path[0] == '\0'
        ) {
            set_error(error, error_len, "maintenance.firewall paths must be set when enabled");
            return 0;
        }
        if (
            config->maintenance_firewall_path[0] != '/'
            || config->maintenance_firewall_backup_path[0] != '/'
        ) {
            set_error(error, error_len, "maintenance.firewall paths must be absolute");
            return 0;
        }
    }
    if (config->maintenance_ipv6_firewall_enabled) {
        if (
            config->maintenance_ipv6_firewall_path[0] == '\0'
            || config->maintenance_ipv6_firewall_backup_path[0] == '\0'
        ) {
            set_error(error, error_len, "maintenance.ipv6Firewall paths must be set when enabled");
            return 0;
        }
        if (
            config->maintenance_ipv6_firewall_path[0] != '/'
            || config->maintenance_ipv6_firewall_backup_path[0] != '/'
        ) {
            set_error(error, error_len, "maintenance.ipv6Firewall paths must be absolute");
            return 0;
        }
    }
    if (config->mqtt_enabled) {
        if (config->mqtt_host[0] == '\0') {
            set_error(error, error_len, "mqtt.host must be set when mqtt.enabled=true");
            return 0;
        }
        if (config->mqtt_client_id[0] == '\0') {
            set_error(error, error_len, "mqtt.clientId must be set when mqtt.enabled=true");
            return 0;
        }
        if (config->mqtt_command_topic[0] != '\0' && config->mqtt_command_host[0] == '\0') {
            set_error(error, error_len, "mqtt.commandHost must be set when command topic is enabled");
            return 0;
        }
        if (config->mqtt_command_topic[0] == '\0' && config->mqtt_event_topic[0] == '\0') {
            set_error(error, error_len, "at least one MQTT command or event topic must be set");
            return 0;
        }
    }
    if (config->mqtt_qos != 0) {
        set_error(error, error_len, "mqtt.qos must be 0");
        return 0;
    }
    if (config->mqtt_keepalive_seconds < 10) {
        set_error(error, error_len, "mqtt.keepaliveSeconds must be >= 10");
        return 0;
    }
    if (config->mqtt_reconnect_initial_seconds < 1) {
        set_error(error, error_len, "mqtt.reconnectInitialSeconds must be >= 1");
        return 0;
    }
    if (config->mqtt_reconnect_max_seconds < config->mqtt_reconnect_initial_seconds) {
        set_error(error, error_len, "mqtt.reconnectMaxSeconds must be >= reconnectInitialSeconds");
        return 0;
    }
    if (config->activations_count < 0 || config->activations_count > C300X_MAX_ACTIVATIONS) {
        set_error(error, error_len, "activations.items exceeds native limit");
        return 0;
    }
    if (config->activation_discovery_root_count < 0
        || config->activation_discovery_root_count > C300X_MAX_ACTIVATION_DISCOVERY_ROOTS) {
        set_error(error, error_len, "activations.discoveryRoots exceeds native limit");
        return 0;
    }
    if (config->activations_auto_discover) {
        for (int index = 0; index < config->activation_discovery_root_count; index++) {
            if (config->activation_discovery_roots[index][0] != '/') {
                set_error(error, error_len, "activations.discoveryRoots entries must be absolute paths");
                return 0;
            }
        }
    }
    for (int index = 0; index < config->activations_count; index++) {
        const struct c300x_activation *activation = &config->activations[index];
        int has_command = activation->press_command[0] != '\0';
        int has_address = activation->address[0] != '\0';
        int auto_address = strcmp(activation->address_mode, "auto") == 0;

        for (int other = index + 1; other < config->activations_count; other++) {
            if (strcmp(activation->id, config->activations[other].id) == 0) {
                set_error(error, error_len, "activations item ids must be unique");
                return 0;
            }
        }
        if (strcmp(activation->type, "unknown") == 0) {
            continue;
        }
        if (strcmp(activation->type, "lock") == 0 && !has_address && !has_command && !auto_address) {
            set_error(error, error_len, "lock activations need address, addressMode=auto or pressCommand");
            return 0;
        }
        if ((strcmp(activation->type, "light") == 0 || strcmp(activation->type, "stair_light") == 0)
            && !has_address
            && !has_command
            && !auto_address) {
            set_error(error, error_len, "light activations need address, addressMode=auto or pressCommand");
            return 0;
        }
        if ((strcmp(activation->type, "generic") == 0 || strcmp(activation->type, "scenario") == 0)
            && !has_command
            && !auto_address) {
            set_error(error, error_len, "generic activations need addressMode=auto or pressCommand");
            return 0;
        }
    }
    if (config->video_rtsp_path[0] == '\0' || config->video_rtsp_video_path[0] == '\0') {
        set_error(error, error_len, "video.rtsp.path and video.rtsp.videoPath must be set");
        return 0;
    }
    if (
        config->answering_machine_messages_enabled
        && config->answering_machine_messages_root[0] == '\0'
    ) {
        set_error(error, error_len, "answeringMachine.messages.root must be set when enabled");
        return 0;
    }
    if (config->answering_machine_messages_max > C300X_MAX_VOICEMAIL_MESSAGES) {
        set_error(error, error_len, "answeringMachine.messages.maxMessages exceeds native limit");
        return 0;
    }
    if (config->system_metrics_sample_interval_seconds < 5) {
        set_error(error, error_len, "systemMetrics.sampleIntervalSeconds must be >= 5");
        return 0;
    }
    if (config->system_metrics_heartbeat_seconds < config->system_metrics_sample_interval_seconds) {
        set_error(error, error_len, "systemMetrics.heartbeatSeconds must be >= sampleIntervalSeconds");
        return 0;
    }
    if (config->system_metrics_change_percent < 1 || config->system_metrics_change_percent > 100) {
        set_error(error, error_len, "systemMetrics.changePercent must be between 1 and 100");
        return 0;
    }
    if (config->memos_enabled && (config->memos_text_root[0] == '\0' || config->memos_voice_root[0] == '\0')) {
        set_error(error, error_len, "memos.textRoot and memos.voiceRoot must be set when enabled");
        return 0;
    }
    if (config->memos_max > C300X_MAX_VOICEMAIL_MESSAGES) {
        set_error(error, error_len, "memos.maxMemos exceeds native limit");
        return 0;
    }
    return 1;
}

static void write_json_string(FILE *file, const char *value)
{
    fputc('"', file);
    for (size_t index = 0; value[index] != '\0'; index++) {
        unsigned char ch = (unsigned char)value[index];
        if (ch == '"' || ch == '\\') {
            fputc('\\', file);
            fputc(ch, file);
        } else if (ch == '\n') {
            fputs("\\n", file);
        } else if (ch == '\r') {
            fputs("\\r", file);
        } else if (ch == '\t') {
            fputs("\\t", file);
        } else if (ch < 0x20) {
            fprintf(file, "\\u%04x", ch);
        } else {
            fputc(ch, file);
        }
    }
    fputc('"', file);
}

static void write_json_string_field(FILE *file, const char *name, const char *value, const char *suffix)
{
    fprintf(file, "    \"%s\": ", name);
    write_json_string(file, value);
    fprintf(file, "%s\n", suffix);
}

static void write_activation_item(
    FILE *file,
    const struct c300x_activation *activation,
    const char *suffix
)
{
    fprintf(file, "      {\"id\": ");
    write_json_string(file, activation->id);
    fprintf(file, ",\"name\": ");
    write_json_string(file, activation->name);
    fprintf(file, ",\"type\": ");
    write_json_string(file, activation->type);
    fprintf(file, ",\"addressMode\": ");
    write_json_string(file, activation->address_mode);
    fprintf(file, ",\"address\": ");
    write_json_string(file, activation->address);
    fprintf(file, ",\"pressCommand\": ");
    write_json_string(file, activation->press_command);
    fprintf(file, ",\"releaseCommand\": ");
    write_json_string(file, activation->release_command);
    fprintf(file, ",\"holdMs\": %d}%s\n", activation->hold_ms, suffix);
}

static const char *persisted_api_token(const struct c300x_config *config)
{
    return config->api_token_from_env ? config->api_file_token : config->api_token;
}

static int activations_equal(
    const struct c300x_activation *left,
    const struct c300x_activation *right
)
{
    return strcmp(left->id, right->id) == 0
        && strcmp(left->name, right->name) == 0
        && strcmp(left->type, right->type) == 0
        && strcmp(left->address_mode, right->address_mode) == 0
        && strcmp(left->address, right->address) == 0
        && strcmp(left->press_command, right->press_command) == 0
        && strcmp(left->release_command, right->release_command) == 0
        && left->hold_ms == right->hold_ms;
}

static int activation_lists_equal(
    const struct c300x_config *left,
    const struct c300x_config *right
)
{
    if (left->activations_enabled != right->activations_enabled
        || left->activations_count != right->activations_count) {
        return 0;
    }
    for (int index = 0; index < left->activations_count; index++) {
        if (!activations_equal(&left->activations[index], &right->activations[index])) {
            return 0;
        }
    }
    return 1;
}

static int activation_discovery_roots_equal(
    const struct c300x_config *left,
    const struct c300x_config *right
)
{
    if (left->activations_auto_discover != right->activations_auto_discover
        || left->activation_discovery_root_count != right->activation_discovery_root_count) {
        return 0;
    }
    for (int index = 0; index < left->activation_discovery_root_count; index++) {
        if (strcmp(left->activation_discovery_roots[index], right->activation_discovery_roots[index]) != 0) {
            return 0;
        }
    }
    return 1;
}

int c300x_config_persisted_equal(
    const struct c300x_config *left,
    const struct c300x_config *right
)
{
#define C300X_EQ_INT(field) (left->field == right->field)
#define C300X_EQ_STR(field) (strcmp(left->field, right->field) == 0)
    return C300X_EQ_STR(listen_host)
        && C300X_EQ_INT(api_port)
        && C300X_EQ_INT(ui_port)
        && C300X_EQ_INT(allow_lan)
        && C300X_EQ_INT(display_bridge_enabled)
        && C300X_EQ_STR(device_model)
        && C300X_EQ_STR(device_firmware)
        && C300X_EQ_STR(home_assistant_webhook_url)
        && C300X_EQ_STR(home_assistant_shared_secret)
        && C300X_EQ_INT(home_assistant_request_timeout_ms)
        && strcmp(persisted_api_token(left), persisted_api_token(right)) == 0
        && C300X_EQ_INT(api_no_auth)
        && C300X_EQ_STR(openwebnet_host)
        && C300X_EQ_INT(openwebnet_port)
        && C300X_EQ_INT(openwebnet_timeout_ms)
        && C300X_EQ_STR(stair_light_default_address)
        && C300X_EQ_STR(lock_name)
        && C300X_EQ_STR(lock_address)
        && C300X_EQ_INT(lock_release_delay_ms)
        && activation_lists_equal(left, right)
        && activation_discovery_roots_equal(left, right)
        && C300X_EQ_INT(maintenance_enabled)
        && C300X_EQ_INT(maintenance_ssh_start_enabled)
        && C300X_EQ_INT(maintenance_reboot_enabled)
        && C300X_EQ_INT(maintenance_reboot_delay_ms)
        && C300X_EQ_INT(maintenance_agent_remove_enabled)
        && C300X_EQ_STR(maintenance_agent_remove_script)
        && C300X_EQ_INT(maintenance_gui_reload_enabled)
        && C300X_EQ_STR(maintenance_gui_reload_script)
        && C300X_EQ_INT(maintenance_qml_patch_enabled)
        && C300X_EQ_STR(maintenance_qml_patch_script)
        && C300X_EQ_INT(maintenance_firewall_enabled)
        && C300X_EQ_INT(maintenance_ipv6_firewall_enabled)
        && C300X_EQ_STR(maintenance_firewall_path)
        && C300X_EQ_STR(maintenance_firewall_backup_path)
        && C300X_EQ_STR(maintenance_ipv6_firewall_path)
        && C300X_EQ_STR(maintenance_ipv6_firewall_backup_path)
        && C300X_EQ_STR(maintenance_admin_token)
        && C300X_EQ_INT(maintenance_no_auth_allowed)
        && C300X_EQ_INT(mdns_enabled)
        && C300X_EQ_STR(mdns_name)
        && C300X_EQ_INT(events_enabled)
        && C300X_EQ_STR(events_group)
        && C300X_EQ_INT(events_port)
        && C300X_EQ_STR(subscription_store_path)
        && C300X_EQ_INT(callback_timeout_ms)
        && C300X_EQ_INT(mqtt_enabled)
        && C300X_EQ_STR(mqtt_host)
        && C300X_EQ_INT(mqtt_port)
        && C300X_EQ_STR(mqtt_username)
        && C300X_EQ_STR(mqtt_password)
        && C300X_EQ_STR(mqtt_client_id)
        && C300X_EQ_STR(mqtt_command_host)
        && C300X_EQ_INT(mqtt_command_port)
        && C300X_EQ_STR(mqtt_command_topic)
        && C300X_EQ_STR(mqtt_event_topic)
        && C300X_EQ_STR(mqtt_json_event_topic)
        && C300X_EQ_STR(mqtt_status_topic)
        && C300X_EQ_STR(mqtt_availability_topic)
        && C300X_EQ_INT(mqtt_qos)
        && C300X_EQ_INT(mqtt_keepalive_seconds)
        && C300X_EQ_INT(mqtt_reconnect_initial_seconds)
        && C300X_EQ_INT(mqtt_reconnect_max_seconds)
        && C300X_EQ_INT(video_enabled)
        && C300X_EQ_STR(video_av_host)
        && C300X_EQ_INT(video_av_port)
        && C300X_EQ_INT(video_av_timeout_ms)
        && C300X_EQ_INT(video_av_high_resolution)
        && C300X_EQ_INT(video_rtsp_port)
        && C300X_EQ_INT(video_rtp_port_start)
        && C300X_EQ_INT(video_rtp_port_count)
        && C300X_EQ_INT(video_rtsp_keep_alive_ms)
        && C300X_EQ_STR(video_rtsp_path)
        && C300X_EQ_STR(video_rtsp_video_path)
        && C300X_EQ_STR(video_rtsp_recorder_path)
        && C300X_EQ_STR(video_rtsp_username)
        && C300X_EQ_STR(video_rtsp_password)
        && C300X_EQ_STR(video_sip_from)
        && C300X_EQ_STR(video_sip_to)
        && C300X_EQ_STR(video_sip_domain)
        && C300X_EQ_STR(video_sip_devaddr)
        && C300X_EQ_STR(video_sip_local_ip)
        && C300X_EQ_INT(video_sip_local_port)
        && C300X_EQ_INT(video_sip_use_tcp)
        && C300X_EQ_INT(video_sip_debug)
        && C300X_EQ_INT(answering_machine_messages_enabled)
        && C300X_EQ_STR(answering_machine_messages_root)
        && C300X_EQ_INT(answering_machine_messages_watch)
        && C300X_EQ_INT(answering_machine_messages_max)
        && C300X_EQ_INT(system_metrics_enabled)
        && C300X_EQ_INT(system_metrics_watch)
        && C300X_EQ_INT(system_metrics_sample_interval_seconds)
        && C300X_EQ_INT(system_metrics_heartbeat_seconds)
        && C300X_EQ_INT(system_metrics_change_percent)
        && C300X_EQ_INT(memos_enabled)
        && C300X_EQ_STR(memos_text_root)
        && C300X_EQ_STR(memos_voice_root)
        && C300X_EQ_INT(memos_watch)
        && C300X_EQ_INT(memos_max);
#undef C300X_EQ_INT
#undef C300X_EQ_STR
}

static int files_equal(const char *left_path, const char *right_path)
{
    FILE *left = fopen(left_path, "rb");
    FILE *right = fopen(right_path, "rb");
    unsigned char left_buffer[4096];
    unsigned char right_buffer[4096];
    int equal = 1;

    if (left == NULL || right == NULL) {
        if (left != NULL) {
            fclose(left);
        }
        if (right != NULL) {
            fclose(right);
        }
        return 0;
    }

    while (1) {
        size_t left_read = fread(left_buffer, 1, sizeof(left_buffer), left);
        size_t right_read = fread(right_buffer, 1, sizeof(right_buffer), right);

        if (left_read != right_read || memcmp(left_buffer, right_buffer, left_read) != 0) {
            equal = 0;
            break;
        }
        if (left_read < sizeof(left_buffer)) {
            if (ferror(left) || ferror(right)) {
                equal = 0;
            }
            break;
        }
    }

    fclose(left);
    fclose(right);
    return equal;
}

static int read_config_file_metadata(
    const char *path,
    mode_t *mode,
    uid_t *uid,
    gid_t *gid
)
{
#ifdef __arm__
    struct stat64 status;

    if (syscall(SYS_stat64, path, &status) != 0) {
        return 0;
    }
#else
    struct stat status;

    if (stat(path, &status) != 0) {
        return 0;
    }
#endif
    if (mode != NULL) {
        *mode = status.st_mode;
    }
    if (uid != NULL) {
        *uid = status.st_uid;
    }
    if (gid != NULL) {
        *gid = status.st_gid;
    }
    return 1;
}

static int ensure_config_mode(
    const char *path,
    char *error,
    size_t error_len,
    int *changed
)
{
    mode_t mode;

    if (!read_config_file_metadata(path, &mode, NULL, NULL)) {
        return 1;
    }
    if ((mode & 0777) == 0600) {
        return 1;
    }
    if (chmod(path, 0600) != 0) {
        set_error(error, error_len, "unable to set config file mode");
        return 0;
    }
    if (changed != NULL) {
        *changed = 1;
    }
    return 1;
}

static int save_config_internal(
    const struct c300x_config *config,
    char *error,
    size_t error_len,
    int *changed
)
{
    char temporary_path[C300X_MAX_PATH_LEN + 8];
    FILE *file;
    uid_t owner_uid = 0;
    gid_t owner_gid = 0;
    int have_owner = 0;

    if (changed != NULL) {
        *changed = 0;
    }
    if (config->config_path[0] == '\0') {
        set_error(error, error_len, "config path is not set");
        return 0;
    }
    if (snprintf(temporary_path, sizeof(temporary_path), "%s.tmp", config->config_path) >= (int)sizeof(temporary_path)) {
        set_error(error, error_len, "config path is too long");
        return 0;
    }
    have_owner = read_config_file_metadata(
        config->config_path,
        NULL,
        &owner_uid,
        &owner_gid
    );
    file = fopen(temporary_path, "w");
    if (file == NULL) {
        set_error(error, error_len, "unable to open temporary config file");
        return 0;
    }

    fprintf(file, "{\n");
    fprintf(file, "  \"listen\": {\n");
    write_json_string_field(file, "host", config->listen_host, ",");
    fprintf(file, "    \"apiPort\": %u,\n", config->api_port);
    fprintf(file, "    \"uiPort\": %u,\n", config->ui_port);
    fprintf(file, "    \"allowLan\": %s\n", config->allow_lan ? "true" : "false");
    fprintf(file, "  },\n");
    fprintf(file, "  \"api\": {\n");
    write_json_string_field(
        file,
        "token",
        config->api_token_from_env ? config->api_file_token : config->api_token,
        ","
    );
    fprintf(file, "    \"noAuth\": %s\n", config->api_no_auth ? "true" : "false");
    fprintf(file, "  },\n");
    fprintf(file, "  \"device\": {\n");
    write_json_string_field(file, "model", config->device_model, ",");
    write_json_string_field(file, "firmware", config->device_firmware, ",");
    write_json_string_field(file, "stairLightDefaultAddress", config->stair_light_default_address, "");
    fprintf(file, "  },\n");
    fprintf(file, "  \"openwebnet\": {\n");
    write_json_string_field(file, "host", config->openwebnet_host, ",");
    fprintf(file, "    \"port\": %u,\n", config->openwebnet_port);
    fprintf(file, "    \"timeoutMs\": %d\n", config->openwebnet_timeout_ms);
    fprintf(file, "  },\n");
    fprintf(file, "  \"activations\": {\n");
    fprintf(file, "    \"enabled\": %s,\n", config->activations_enabled ? "true" : "false");
    fprintf(file, "    \"autoDiscover\": %s,\n", config->activations_auto_discover ? "true" : "false");
    fprintf(file, "    \"discoveryRoots\": [");
    for (int index = 0; index < config->activation_discovery_root_count; index++) {
        fprintf(file, "%s", index == 0 ? "" : ",");
        write_json_string(file, config->activation_discovery_roots[index]);
    }
    fprintf(file, "],\n");
    fprintf(file, "    \"items\": [\n");
    for (int index = 0; index < config->activations_count; index++) {
        write_activation_item(
            file,
            &config->activations[index],
            index + 1 < config->activations_count ? "," : ""
        );
    }
    fprintf(file, "    ]\n");
    fprintf(file, "  },\n");
    fprintf(file, "  \"locks\": {\n");
    fprintf(file, "    \"releaseDelayMs\": %d,\n", config->lock_release_delay_ms);
    fprintf(file, "    \"items\": {\n");
    fprintf(file, "      \"default\": {\n");
    fprintf(file, "        \"name\": ");
    write_json_string(file, config->lock_name);
    fprintf(file, ",\n        \"address\": ");
    write_json_string(file, config->lock_address);
    fprintf(file, "\n      }\n    }\n  },\n");
    fprintf(file, "  \"maintenance\": {\n");
    fprintf(file, "    \"enabled\": %s,\n", config->maintenance_enabled ? "true" : "false");
    write_json_string_field(file, "adminToken", config->maintenance_admin_token, ",");
    fprintf(file, "    \"sshStart\": {\"enabled\": %s},\n", config->maintenance_ssh_start_enabled ? "true" : "false");
    fprintf(file, "    \"reboot\": {\"enabled\": %s,\"delayMs\": %d},\n", config->maintenance_reboot_enabled ? "true" : "false", config->maintenance_reboot_delay_ms);
    fprintf(file, "    \"agentRemove\": {\"enabled\": %s,\"script\": ", config->maintenance_agent_remove_enabled ? "true" : "false");
    write_json_string(file, config->maintenance_agent_remove_script);
    fprintf(file, "},\n");
    fprintf(file, "    \"guiReload\": {\"enabled\": %s,\"script\": ", config->maintenance_gui_reload_enabled ? "true" : "false");
    write_json_string(file, config->maintenance_gui_reload_script);
    fprintf(file, "},\n");
    fprintf(file, "    \"qmlPatch\": {\"enabled\": %s,\"script\": ", config->maintenance_qml_patch_enabled ? "true" : "false");
    write_json_string(file, config->maintenance_qml_patch_script);
    fprintf(file, "},\n");
    fprintf(file, "    \"firewall\": {\"enabled\": %s,\"path\": ", config->maintenance_firewall_enabled ? "true" : "false");
    write_json_string(file, config->maintenance_firewall_path);
    fprintf(file, ",\"backupPath\": ");
    write_json_string(file, config->maintenance_firewall_backup_path);
    fprintf(file, "},\n");
    fprintf(file, "    \"ipv6Firewall\": {\"enabled\": %s,\"path\": ", config->maintenance_ipv6_firewall_enabled ? "true" : "false");
    write_json_string(file, config->maintenance_ipv6_firewall_path);
    fprintf(file, ",\"backupPath\": ");
    write_json_string(file, config->maintenance_ipv6_firewall_backup_path);
    fprintf(file, "},\n");
    fprintf(file, "    \"allowNoAuth\": %s\n  },\n", config->maintenance_no_auth_allowed ? "true" : "false");
    fprintf(file, "  \"mdns\": {\"enabled\": %s,\"name\": ", config->mdns_enabled ? "true" : "false");
    write_json_string(file, config->mdns_name);
    fprintf(file, "},\n");
    fprintf(file, "  \"events\": {\n");
    write_json_string_field(file, "subscriptionStorePath", config->subscription_store_path, ",");
    fprintf(file, "    \"callbackTimeoutMs\": %d,\n", config->callback_timeout_ms);
    fprintf(file, "    \"udp\": {\"enabled\": %s,\"group\": ", config->events_enabled ? "true" : "false");
    write_json_string(file, config->events_group);
    fprintf(file, ",\"port\": %u}\n  },\n", config->events_port);
    fprintf(file, "  \"mqtt\": {\n");
    fprintf(file, "    \"enabled\": %s,\n", config->mqtt_enabled ? "true" : "false");
    write_json_string_field(file, "host", config->mqtt_host, ",");
    fprintf(file, "    \"port\": %u,\n", config->mqtt_port);
    write_json_string_field(file, "username", config->mqtt_username, ",");
    write_json_string_field(file, "password", config->mqtt_password, ",");
    write_json_string_field(file, "clientId", config->mqtt_client_id, ",");
    write_json_string_field(file, "commandHost", config->mqtt_command_host, ",");
    fprintf(file, "    \"commandPort\": %u,\n", config->mqtt_command_port);
    fprintf(file, "    \"topics\": {\"command\": ");
    write_json_string(file, config->mqtt_command_topic);
    fprintf(file, ",\"event\": ");
    write_json_string(file, config->mqtt_event_topic);
    fprintf(file, ",\"jsonEvent\": ");
    write_json_string(file, config->mqtt_json_event_topic);
    fprintf(file, ",\"status\": ");
    write_json_string(file, config->mqtt_status_topic);
    fprintf(file, ",\"availability\": ");
    write_json_string(file, config->mqtt_availability_topic);
    fprintf(file, "},\n");
    fprintf(
        file,
        "    \"qos\": %d,\n    \"keepaliveSeconds\": %d,\n    \"reconnectInitialSeconds\": %d,\n    \"reconnectMaxSeconds\": %d\n  },\n",
        config->mqtt_qos,
        config->mqtt_keepalive_seconds,
        config->mqtt_reconnect_initial_seconds,
        config->mqtt_reconnect_max_seconds
    );
    fprintf(file, "  \"answeringMachine\": {\n");
    fprintf(file, "    \"messages\": {\"enabled\": %s,\"root\": ", config->answering_machine_messages_enabled ? "true" : "false");
    write_json_string(file, config->answering_machine_messages_root);
    fprintf(file, ",\"watch\": %s,\"maxMessages\": %d}\n  },\n", config->answering_machine_messages_watch ? "true" : "false", config->answering_machine_messages_max);
    fprintf(file, "  \"memos\": {\n");
    fprintf(file, "    \"enabled\": %s,\n", config->memos_enabled ? "true" : "false");
    write_json_string_field(file, "textRoot", config->memos_text_root, ",");
    write_json_string_field(file, "voiceRoot", config->memos_voice_root, ",");
    fprintf(file, "    \"watch\": %s,\n", config->memos_watch ? "true" : "false");
    fprintf(file, "    \"maxMemos\": %d\n  },\n", config->memos_max);
    fprintf(file, "  \"systemMetrics\": {\"enabled\": %s,\"watch\": %s,\"sampleIntervalSeconds\": %d,\"heartbeatSeconds\": %d,\"changePercent\": %d},\n", config->system_metrics_enabled ? "true" : "false", config->system_metrics_watch ? "true" : "false", config->system_metrics_sample_interval_seconds, config->system_metrics_heartbeat_seconds, config->system_metrics_change_percent);
    fprintf(file, "  \"video\": {\n");
    fprintf(file, "    \"enabled\": %s,\n", config->video_enabled ? "true" : "false");
    fprintf(file, "    \"av\": {\"host\": ");
    write_json_string(file, config->video_av_host);
    fprintf(file, ",\"port\": %u,\"timeoutMs\": %d,\"highResolution\": %s},\n", config->video_av_port, config->video_av_timeout_ms, config->video_av_high_resolution ? "true" : "false");
    fprintf(file, "    \"sip\": {\"from\": ");
    write_json_string(file, config->video_sip_from);
    fprintf(file, ",\"to\": ");
    write_json_string(file, config->video_sip_to);
    fprintf(file, ",\"domain\": ");
    write_json_string(file, config->video_sip_domain);
    fprintf(file, ",\"devaddr\": ");
    write_json_string(file, config->video_sip_devaddr);
    fprintf(file, ",\"localIp\": ");
    write_json_string(file, config->video_sip_local_ip);
    fprintf(file, ",\"localPort\": %u,\"useTcp\": %s,\"debug\": %s},\n", config->video_sip_local_port, config->video_sip_use_tcp ? "true" : "false", config->video_sip_debug ? "true" : "false");
    fprintf(file, "    \"rtsp\": {\"port\": %u,\"path\": ", config->video_rtsp_port);
    write_json_string(file, config->video_rtsp_path);
    fprintf(file, ",\"videoPath\": ");
    write_json_string(file, config->video_rtsp_video_path);
    fprintf(file, ",\"recorderPath\": ");
    write_json_string(file, config->video_rtsp_recorder_path);
    fprintf(file, ",\"username\": ");
    write_json_string(file, config->video_rtsp_username);
    fprintf(file, ",\"password\": ");
    write_json_string(file, config->video_rtsp_password);
    fprintf(file, ",\"keepAliveMs\": %d,\"rtpPortStart\": %u,\"rtpPortCount\": %d}\n  },\n", config->video_rtsp_keep_alive_ms, config->video_rtp_port_start, config->video_rtp_port_count);
    fprintf(file, "  \"displayBridge\": {\n");
    fprintf(file, "    \"enabled\": %s,\n", config->display_bridge_enabled ? "true" : "false");
    fprintf(file, "    \"homeAssistant\": {\"webhookUrl\": ");
    write_json_string(file, config->home_assistant_webhook_url);
    fprintf(file, ",\"sharedSecret\": ");
    write_json_string(file, config->home_assistant_shared_secret);
    fprintf(file, ",\"requestTimeoutMs\": %d}\n  }\n}\n", config->home_assistant_request_timeout_ms);

    if (fclose(file) != 0) {
        (void)unlink(temporary_path);
        set_error(error, error_len, "unable to write temporary config file");
        return 0;
    }
    (void)chmod(temporary_path, 0600);
    if (have_owner && chown(temporary_path, owner_uid, owner_gid) != 0 && errno != EPERM) {
        (void)unlink(temporary_path);
        set_error(error, error_len, "unable to preserve config file owner");
        return 0;
    }
    if (files_equal(temporary_path, config->config_path)) {
        (void)unlink(temporary_path);
        return ensure_config_mode(config->config_path, error, error_len, changed);
    }
    if (rename(temporary_path, config->config_path) != 0) {
        (void)unlink(temporary_path);
        set_error(error, error_len, "unable to replace config file");
        return 0;
    }
    (void)chmod(config->config_path, 0600);
    if (changed != NULL) {
        *changed = 1;
    }
    return 1;
}

int c300x_save_config(
    const struct c300x_config *config,
    char *error,
    size_t error_len
)
{
    return save_config_internal(config, error, error_len, NULL);
}

int c300x_save_config_if_changed(
    const struct c300x_config *config,
    char *error,
    size_t error_len,
    int *changed
)
{
    return save_config_internal(config, error, error_len, changed);
}
