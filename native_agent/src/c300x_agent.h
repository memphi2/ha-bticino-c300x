#ifndef C300X_AGENT_H
#define C300X_AGENT_H

#include <stddef.h>
#include <stdint.h>

#ifndef C300X_NATIVE_AGENT_VERSION
#define C300X_NATIVE_AGENT_VERSION "0.0.0-dev"
#endif
#define C300X_MAX_HOST_LEN 64
#define C300X_MAX_TOKEN_LEN 256
#define C300X_MAX_ADDRESS_LEN 32
#define C300X_MAX_MODEL_LEN 32
#define C300X_MAX_VERSION_LEN 64
#define C300X_MAX_LOCK_ID_LEN 32
#define C300X_MAX_LOCK_NAME_LEN 64
#define C300X_ACTIVATION_ID_MAX_CHARS 32
#define C300X_MAX_ACTIVATION_ID_LEN (C300X_ACTIVATION_ID_MAX_CHARS + 1)
#define C300X_MAX_ACTIVATION_NAME_LEN 64
#define C300X_MAX_ACTIVATION_TYPE_LEN 24
#define C300X_MAX_ACTIVATION_ADDRESS_MODE_LEN 8
#define C300X_MAX_ACTIVATIONS 16
#define C300X_MAX_ACTIVATION_DISCOVERY_ROOTS 4
#define C300X_MAX_DISCOVERED_ACTIVATIONS 16
#define C300X_MAX_FRAME_LEN 256
#define C300X_MAX_ERROR_LEN 256
#define C300X_MAX_PATH_LEN 256
#define C300X_MAX_VOICEMAIL_ID_LEN 65
#define C300X_MAX_VOICEMAIL_MESSAGES 64
#define C300X_MAX_MEMO_TEXT_LEN 512

struct c300x_activation {
    char id[C300X_MAX_ACTIVATION_ID_LEN];
    char name[C300X_MAX_ACTIVATION_NAME_LEN];
    char type[C300X_MAX_ACTIVATION_TYPE_LEN];
    char address_mode[C300X_MAX_ACTIVATION_ADDRESS_MODE_LEN];
    char address[C300X_MAX_ADDRESS_LEN];
    char press_command[C300X_MAX_FRAME_LEN];
    char release_command[C300X_MAX_FRAME_LEN];
    int hold_ms;
};

struct c300x_config {
    char listen_host[C300X_MAX_HOST_LEN];
    uint16_t api_port;
    uint16_t ui_port;
    int allow_lan;
    int display_bridge_enabled;
    char config_path[C300X_MAX_PATH_LEN];
    char device_model[C300X_MAX_MODEL_LEN];
    char device_firmware[C300X_MAX_VERSION_LEN];
    char home_assistant_webhook_url[C300X_MAX_PATH_LEN];
    char home_assistant_shared_secret[C300X_MAX_TOKEN_LEN];
    int home_assistant_request_timeout_ms;
    char api_token[C300X_MAX_TOKEN_LEN];
    char api_file_token[C300X_MAX_TOKEN_LEN];
    int api_token_from_env;
    int api_no_auth;
    int restart_required;
    char openwebnet_host[C300X_MAX_HOST_LEN];
    uint16_t openwebnet_port;
    int openwebnet_timeout_ms;
    char stair_light_default_address[C300X_MAX_ADDRESS_LEN];
    char lock_id[C300X_MAX_LOCK_ID_LEN];
    char lock_name[C300X_MAX_LOCK_NAME_LEN];
    char lock_address[C300X_MAX_ADDRESS_LEN];
    int lock_release_delay_ms;
    int activations_enabled;
    int activations_auto_discover;
    int activation_discovery_root_count;
    char activation_discovery_roots[C300X_MAX_ACTIVATION_DISCOVERY_ROOTS][C300X_MAX_PATH_LEN];
    int activations_count;
    struct c300x_activation activations[C300X_MAX_ACTIVATIONS];
    int maintenance_enabled;
    int maintenance_ssh_start_enabled;
    int maintenance_reboot_enabled;
    int maintenance_reboot_delay_ms;
    int maintenance_agent_remove_enabled;
    char maintenance_agent_remove_script[C300X_MAX_PATH_LEN];
    int maintenance_gui_reload_enabled;
    char maintenance_gui_reload_script[C300X_MAX_PATH_LEN];
    int maintenance_qml_patch_enabled;
    char maintenance_qml_patch_script[C300X_MAX_PATH_LEN];
    int maintenance_firewall_enabled;
    int maintenance_ipv6_firewall_enabled;
    char maintenance_firewall_path[C300X_MAX_PATH_LEN];
    char maintenance_firewall_backup_path[C300X_MAX_PATH_LEN];
    char maintenance_ipv6_firewall_path[C300X_MAX_PATH_LEN];
    char maintenance_ipv6_firewall_backup_path[C300X_MAX_PATH_LEN];
    char maintenance_admin_token[C300X_MAX_TOKEN_LEN];
    int maintenance_no_auth_allowed;
    int mdns_enabled;
    char mdns_name[C300X_MAX_MODEL_LEN];
    int events_enabled;
    char events_group[C300X_MAX_HOST_LEN];
    uint16_t events_port;
    char subscription_store_path[C300X_MAX_PATH_LEN];
    int callback_timeout_ms;
    int mqtt_enabled;
    char mqtt_host[C300X_MAX_HOST_LEN];
    uint16_t mqtt_port;
    char mqtt_username[C300X_MAX_TOKEN_LEN];
    char mqtt_password[C300X_MAX_TOKEN_LEN];
    char mqtt_client_id[C300X_MAX_TOKEN_LEN];
    char mqtt_command_host[C300X_MAX_HOST_LEN];
    uint16_t mqtt_command_port;
    char mqtt_command_topic[C300X_MAX_PATH_LEN];
    char mqtt_event_topic[C300X_MAX_PATH_LEN];
    char mqtt_json_event_topic[C300X_MAX_PATH_LEN];
    char mqtt_status_topic[C300X_MAX_PATH_LEN];
    char mqtt_availability_topic[C300X_MAX_PATH_LEN];
    int mqtt_qos;
    int mqtt_keepalive_seconds;
    int mqtt_reconnect_initial_seconds;
    int mqtt_reconnect_max_seconds;
    int video_enabled;
    char video_av_host[C300X_MAX_HOST_LEN];
    uint16_t video_av_port;
    int video_av_timeout_ms;
    int video_av_high_resolution;
    uint16_t video_rtsp_port;
    uint16_t video_rtp_port_start;
    int video_rtp_port_count;
    int video_rtsp_keep_alive_ms;
    char video_rtsp_path[C300X_MAX_PATH_LEN];
    char video_rtsp_video_path[C300X_MAX_PATH_LEN];
    char video_rtsp_recorder_path[C300X_MAX_PATH_LEN];
    char video_rtsp_username[C300X_MAX_TOKEN_LEN];
    char video_rtsp_password[C300X_MAX_TOKEN_LEN];
    char video_sip_from[C300X_MAX_PATH_LEN];
    char video_sip_to[C300X_MAX_PATH_LEN];
    char video_sip_domain[C300X_MAX_HOST_LEN];
    char video_sip_devaddr[C300X_MAX_ADDRESS_LEN];
    char video_sip_local_ip[C300X_MAX_HOST_LEN];
    uint16_t video_sip_local_port;
    int video_sip_use_tcp;
    int video_sip_debug;
    int answering_machine_messages_enabled;
    char answering_machine_messages_root[C300X_MAX_PATH_LEN];
    int answering_machine_messages_watch;
    int answering_machine_messages_max;
    int system_metrics_enabled;
    int system_metrics_watch;
    int system_metrics_sample_interval_seconds;
    int system_metrics_heartbeat_seconds;
    int system_metrics_change_percent;
    int memos_enabled;
    char memos_text_root[C300X_MAX_PATH_LEN];
    char memos_voice_root[C300X_MAX_PATH_LEN];
    int memos_watch;
    int memos_max;
};

void c300x_default_config(struct c300x_config *config);
int c300x_load_config(
    const char *config_path,
    struct c300x_config *config,
    char *error,
    size_t error_len
);
int c300x_save_config(
    const struct c300x_config *config,
    char *error,
    size_t error_len
);
int c300x_save_config_if_changed(
    const struct c300x_config *config,
    char *error,
    size_t error_len,
    int *changed
);
int c300x_config_persisted_equal(
    const struct c300x_config *left,
    const struct c300x_config *right
);
int c300x_run(struct c300x_config *config);
int c300x_openwebnet_send(
    const struct c300x_config *config,
    const char *command,
    char *reply,
    size_t reply_len,
    char *error,
    size_t error_len
);
int c300x_openwebnet_sequence(
    const struct c300x_config *config,
    const char *first_command,
    int delay_ms,
    const char *second_command,
    char *error,
    size_t error_len
);

#endif
