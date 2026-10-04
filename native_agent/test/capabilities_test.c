#include "../src/capabilities.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    struct c300x_config config = {0};
    struct c300x_capabilities_context context = {
        .device_id = "synthetic-id",
        .device_firmware = "1.7.19\"test",
        .bundle_hash = "",
        .activations_count = 3,
        .ringer_min_volume = 0,
        .ringer_max_volume = 10,
        .ringer_volume_step = 1,
    };
    char body[32768];
    char short_body[16];
    strcpy(config.device_model, "C300X");
    strcpy(config.video_rtsp_video_path, "/doorbell\"video");
    strcpy(config.video_rtsp_path, "/audio");
    strcpy(config.video_rtsp_recorder_path, "/recorder");
    strcpy(config.lock_id, "front");
    strcpy(config.lock_name, "Front \"door\"\\entry");
    strcpy(config.stair_light_default_address, "0");
    config.video_enabled = 1;
    config.activations_enabled = 1;
    config.answering_machine_messages_enabled = 1;
    config.answering_machine_messages_watch = 1;
    config.memos_enabled = 1;
    config.memos_watch = 1;
    config.system_metrics_enabled = 1;
    config.system_metrics_watch = 1;
    config.system_metrics_sample_interval_seconds = 30;
    config.system_metrics_heartbeat_seconds = 600;
    config.system_metrics_change_percent = 5;
    config.maintenance_ssh_start_enabled = 1;
    config.maintenance_reboot_enabled = 1;
    config.maintenance_agent_remove_enabled = 1;
    config.maintenance_gui_reload_enabled = 1;
    config.maintenance_firewall_enabled = 1;
    config.maintenance_ipv6_firewall_enabled = 1;
    config.maintenance_qml_patch_enabled = 1;
    config.display_bridge_enabled = 1;

    assert(!c300x_capabilities_json(&config, &context, NULL, 0));
    assert(!c300x_capabilities_json(&config, &context, short_body, sizeof(short_body)));
    assert(short_body[sizeof(short_body) - 1] == '\0');
    for (int maintenance = 0; maintenance <= 1; maintenance++) {
        context.maintenance_supported = maintenance;
        for (int pcmu = 0; pcmu <= 1; pcmu++) {
            context.device_codec_pcmu = pcmu;
            assert(c300x_capabilities_json(&config, &context, body, sizeof(body)));
            fputs(body, stdout);
        }
    }
    config.video_enabled = 0;
    config.activations_enabled = 0;
    config.answering_machine_messages_enabled = 0;
    config.memos_enabled = 0;
    config.system_metrics_enabled = 0;
    assert(c300x_capabilities_json(&config, &context, body, sizeof(body)));
    fputs(body, stdout);
    return 0;
}
