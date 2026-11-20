#include <stdio.h>

#include "../src/c300x_agent.h"

int main(int argc, char **argv)
{
    struct c300x_config config;
    char error[256] = "";

    if (argc != 2 || !c300x_load_config(argv[1], &config, error, sizeof(error))) {
        printf("error %s\n", error);
        return 1;
    }
    printf("{\"high_resolution\":%d,\"qt5\":%d,\"display_patch\":%d}\n",
        config.video_av_high_resolution, c300x_device_display_is_qt5(),
        config.maintenance_qml_patch_enabled);
    return 0;
}
