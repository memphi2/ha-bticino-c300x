#include "capabilities.h"

#include "json_util.h"
#include "video_rtsp.h"

#include <stdio.h>
#include <string.h>

#define C300X_MAX_PATH_JSON_LEN ((C300X_MAX_PATH_LEN * 6) + 1)
#define C300X_JSON_QUOTED_LEN(value_len) (((value_len) * 6) + 3)
#define C300X_AGENT_BUNDLE_HASH_LEN 96

int c300x_capabilities_json(
    const struct c300x_config *config,
    const struct c300x_capabilities_context *context,
    char *body,
    size_t body_len
)
{
    char video_path[C300X_MAX_PATH_JSON_LEN];
    char audio_path[C300X_MAX_PATH_JSON_LEN];
    char recorder_path[C300X_MAX_PATH_JSON_LEN];
    char device_id_json[128];
    char device_model[128];
    char display_kind[64];
    char device_firmware[384];
    char stair_address[128];
    char lock_id[128];
    char lock_name[384];
    char bundle_hash_json[C300X_JSON_QUOTED_LEN(C300X_AGENT_BUNDLE_HASH_LEN)];
    int maintenance_supported = context->maintenance_supported;
    const char *maintenance = maintenance_supported ? "true" : "false";
    int codec_apply_allowed = context->device_model == NULL || strcmp(context->device_model, "C100X") != 0;
    int activations_count = context->activations_count;
    int written;

    c300x_json_escape_string(context->device_id, device_id_json, sizeof(device_id_json));
    c300x_json_escape_string(config->video_rtsp_video_path, video_path, sizeof(video_path));
    c300x_json_escape_string(config->video_rtsp_path, audio_path, sizeof(audio_path));
    c300x_json_escape_string(config->video_rtsp_recorder_path, recorder_path, sizeof(recorder_path));
    c300x_json_escape_string(context->device_model, device_model, sizeof(device_model));
    c300x_json_escape_string(context->display_kind, display_kind, sizeof(display_kind));
    c300x_json_escape_string(context->device_firmware, device_firmware, sizeof(device_firmware));
    c300x_json_escape_string(config->stair_light_default_address, stair_address, sizeof(stair_address));
    c300x_json_escape_string(config->lock_id, lock_id, sizeof(lock_id));
    c300x_json_escape_string(config->lock_name, lock_name, sizeof(lock_name));
    c300x_json_string(context->bundle_hash, bundle_hash_json, sizeof(bundle_hash_json));
    written = snprintf(
        body,
        body_len,
        "{"
        "\"api_version\":\"1\","
        "\"agent\":{\"implementation\":\"native-c\",\"version\":\"%s\",\"api_version\":\"1\",\"bundle_hash\":%s,\"self_update_supported\":%s,\"self_update_file_set_version\":7},"
        "\"device\":{\"id\":\"%s\",\"model\":\"%s\",\"display_kind\":\"%s\",\"firmware\":\"%s\"},"
        "\"capabilities\":{"
        "\"doorbell_events\":true,"
        "\"camera_picture\":{\"supported\":%s},"
        "\"https_callbacks\":%s,"
        "\"https_callbacks_configurable\":true,"
        "\"https_callbacks_enabled\":%s,"
        "\"https_callbacks_configured\":%s,"
        "\"doorbell_video\":{\"supported\":%s,\"stream_path\":\"%s\",\"audio_stream_path\":\"%s\",\"recorder_stream_path\":\"%s\",\"audio_codec\":\"%s\",\"talkback_supported\":true,\"talkback_codec\":\"%s\",\"talkback_payload_type\":%d},"
        "\"doorbell_call\":{\"supported\":%s,\"answer\":true,\"hangup\":true,\"status\":true,\"capture\":false},"
        "\"home_call\":{\"supported\":%s,\"audio_codec\":\"%s\",\"rtp_proxy_supported\":true,\"max_duration_seconds\":%d},"
        "\"stair_light\":{\"supported\":true,\"default_address\":\"%s\"},"
        "\"locks\":{\"supported\":true,\"default_id\":\"%s\",\"locks\":[{\"id\":\"%s\",\"name\":\"%s\"}]},"
        "\"activations\":{\"supported\":%s,\"count\":%d},"
        "\"call_events\":false,"
        "\"announcements\":{\"supported\":%s},"
        "\"ringer\":{\"supported\":true,\"mute\":%s,\"volume\":true,\"min_volume\":%d,\"max_volume\":%d,\"step\":%d},"
        "\"smartphone_forwarding\":{\"supported\":true,\"modes\":[\"enabled\",\"homeassistant\",\"blocked\"]},"
        "\"answering_machine\":{\"supported\":true,\"status\":true,\"greeting_message\":true,\"messages\":{\"supported\":%s,\"source\":\"local_files\",\"watch\":%s,\"media\":%s,\"delete\":%s}},"
        "\"memos\":{\"supported\":%s,\"text\":true,\"voice\":true,\"media\":%s,\"source\":\"local_files\",\"watch\":%s,\"delete\":%s,\"write_text\":%s},"
        "\"system_metrics\":{\"supported\":%s,\"cpu\":true,\"load\":true,\"memory\":true,\"temperature\":true,\"watch\":%s,\"sample_interval_seconds\":%d,\"heartbeat_seconds\":%d,\"change_percent\":%d},"
        "\"mqtt\":{\"supported\":true,\"enabled\":%s,\"configured\":%s},"
        "\"diagnostics\":{\"supported\":true,\"writes\":true,\"runtime\":true},"
        "\"device_user\":{\"supported\":true},"
        "\"auth\":{\"supported\":true,\"configurable\":true,\"no_auth\":%s,\"api_token_configured\":%s,\"maintenance_token_configured\":%s},"
        "\"maintenance\":{\"supported\":%s,\"ssh_start\":%s,\"ssh_stop\":%s,\"ssh_status\":%s,\"reboot\":%s,\"agent_remove\":%s,\"agent_restart\":%s,\"agent_update\":%s,\"config_normalize\":%s,\"device_user_status\":%s,\"device_user_ensure\":%s,\"mqtt_status\":%s,\"mqtt_config\":%s,\"legacy_mqtt_status\":%s,\"legacy_mqtt_config\":%s,\"legacy_mqtt_migrate\":%s,\"gui_reload\":%s,\"firewall_status\":%s,\"firewall_apply\":%s,\"firewall_restore\":%s,\"ipv6_firewall_status\":%s,\"ipv6_firewall_apply\":%s,\"ipv6_firewall_restore\":%s,\"qml_status\":%s,\"qml_patch\":%s,\"qml_core_patch\":%s,\"qml_core_restore\":%s,\"qml_restore\":%s,\"audio_codec_status\":%s,\"audio_codec_apply\":%s,\"audio_codec_restore\":%s,\"camera_resolution\":%s,\"camera_quality\":%s},"
        "\"touch_tone\":{\"supported\":%s,\"requires_display_patch\":true},"
        "\"display_alerts\":%s,"
        "\"memo_led\":%s,"
        "\"display_bridge\":{\"supported\":%s,\"configurable\":%s,\"configured\":%s}"
        "}"
        "}\n",
        C300X_NATIVE_AGENT_VERSION,
        bundle_hash_json,
        maintenance,
        device_id_json,
        device_model,
        display_kind,
        device_firmware,
        context->picture_supported ? "true" : "false",
        context->https_callbacks ? "true" : "false",
        context->https_callbacks_enabled ? "true" : "false",
        config->https_callbacks_enabled ? "true" : "false",
        config->video_enabled ? "true" : "false",
        video_path,
        audio_path,
        recorder_path,
        C300X_RTSP_AUDIO_CODEC,
        context->device_codec_pcmu ? "PCMU/8000" : C300X_TALKBACK_CODEC,
        context->device_codec_pcmu ? 0 : C300X_TALKBACK_RTP_PAYLOAD_TYPE,
        config->video_enabled ? "true" : "false",
        config->video_enabled ? "true" : "false",
        C300X_RTSP_AUDIO_CODEC,
        C300X_HOME_CALL_MAX_DURATION_SECONDS,
        stair_address,
        lock_id,
        lock_id,
        lock_name,
        (config->activations_enabled && activations_count > 0) ? "true" : "false",
        activations_count,
        context->announcements_supported ? "true" : "false",
        context->display_features ? "true" : "false",
        context->ringer_min_volume,
        context->ringer_max_volume,
        context->ringer_volume_step,
        config->answering_machine_messages_enabled ? "true" : "false",
        (config->answering_machine_messages_enabled && config->answering_machine_messages_watch) ? "true" : "false",
        config->answering_machine_messages_enabled ? "true" : "false",
        config->answering_machine_messages_enabled ? "true" : "false",
        config->memos_enabled ? "true" : "false",
        config->memos_enabled ? "true" : "false",
        (config->memos_enabled && config->memos_watch) ? "true" : "false",
        config->memos_enabled ? "true" : "false",
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
        maintenance,
        (maintenance_supported && config->maintenance_ssh_start_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_ssh_start_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_ssh_start_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_reboot_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_agent_remove_enabled) ? "true" : "false",
        maintenance,
        maintenance,
        maintenance,
        maintenance,
        maintenance,
        maintenance,
        maintenance,
        maintenance,
        maintenance,
        maintenance,
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
        (maintenance_supported && config->maintenance_qml_patch_enabled) ? "true" : "false",
        (maintenance_supported && config->maintenance_qml_patch_enabled) ? "true" : "false",
        maintenance,
        (maintenance_supported && codec_apply_allowed) ? "true" : "false",
        /* Explicit recovery is checked against the managed backups by the core. */
        maintenance,
        (maintenance_supported && config->video_enabled && !context->camera_resolution_fixed) ? "true" : "false",
        /* Firmware 3.0.x too: there it sets the low stream. */
        (maintenance_supported && config->video_enabled) ? "true" : "false",
        context->display_features ? "true" : "false",
        context->display_features ? "true" : "false",
        context->memo_led_present ? "true" : "false",
        context->display_features ? "true" : "false",
        context->display_features ? "true" : "false",
        config->display_bridge_enabled ? "true" : "false"
    );
    return written >= 0 && (size_t)written < body_len;
}
