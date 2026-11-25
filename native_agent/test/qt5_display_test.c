#include <stdio.h>
#include <stdlib.h>

#include "../src/c300x_agent.h"
#include "../src/device_detect.h"

int main(int argc, char **argv)
{
    struct c300x_config config;
    char error[256] = "";
    int saved = -1, changed = 0;

    if (argc < 2 || argc > 3 || !c300x_load_config(argv[1], &config, error, sizeof(error))) {
        printf("error %s\n", error);
        return 1;
    }
    if (argc == 3) {
        saved = c300x_save_camera_high_resolution(&config, atoi(argv[2]), error, sizeof(error), &changed);
    }
    printf("{\"high_resolution\":%d,\"resolution_fixed\":%d,\"files_patchable\":%d,"
        "\"model\":\"%s\",\"display_kind\":\"%s\",\"display_patch\":%d,\"gui_reload\":%d,"
        "\"restartable\":%d,\"saved\":%d,\"changed\":%d,\"profile\":[%d,%d,%d]}\n",
        config.video_av_high_resolution, c300x_device_camera_resolution_fixed(),
        c300x_device_display_files_patchable(), c300x_device_model_name(c300x_device_model()),
        c300x_display_kind_name(c300x_device_display_kind()),
        config.maintenance_qml_patch_enabled, config.maintenance_gui_reload_enabled,
        c300x_device_display_restartable(), saved, changed,
        (int)c300x_device_profile().model, (int)c300x_device_profile().display, c300x_device_profile().camera_fixed);
    return 0;
}
