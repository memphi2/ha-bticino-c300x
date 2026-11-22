#include "../src/self_test.h"
#include "../src/device_user.h"
#include "../src/device_routing.h"
#include "../src/string_util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int routing_patched;

int c300x_device_routing_read_status(struct c300x_device_routing_status *status)
{
    memset(status, 0, sizeof(*status));
    status->supported = 1;
    status->patched = routing_patched;
    c300x_copy_string(status->state, sizeof(status->state), routing_patched ? "patched" : "stock");
    return 1;
}

int main(int argc, char **argv)
{
    struct c300x_config config = {0};
    struct c300x_video_status video = {0};
    struct c300x_device_user_identity identity;
    char json[8192];

    if (argc != 3) {
        return 2;
    }
    routing_patched = atoi(argv[2]);
    config.video_enabled = 1;
    config.video_rtsp_port = 6554;
    c300x_copy_string(config.device_firmware, sizeof(config.device_firmware), "1.7.19");
    c300x_copy_string(config.video_rtsp_path, sizeof(config.video_rtsp_path), "/doorbell");
    c300x_copy_string(config.maintenance_firewall_path, sizeof(config.maintenance_firewall_path), argv[1]);
    video.enabled = 1;
    video.running = 1;
    video.bridge_running = 1;
    if (!c300x_self_test_json(&config, &video, 1, 1, json, sizeof(json))) {
        return 3;
    }
    printf("{\"identity_available\":%s,\"self_test\":%s}\n",
           c300x_device_user_media_identity(NULL, &identity) ? "true" : "false", json);
    return 0;
}
