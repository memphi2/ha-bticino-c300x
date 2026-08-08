#ifndef C300X_AGENT_UPDATE_PATHS_H
#define C300X_AGENT_UPDATE_PATHS_H

#include <stddef.h>
#include <string.h>
#include <sys/types.h>

struct c300x_agent_update_file {
    const char *path;
    mode_t mode;
    int optional;
};

static const struct c300x_agent_update_file C300X_AGENT_UPDATE_FILES[] = {
    {"device_agent/armhf/c300x-agent-native", 0700, 0},
    {"device_agent/scripts/qml_patch.sh", 0700, 0},
    {"device_agent/scripts/remove_agent.sh", 0700, 0},
    {"device_agent/scripts/bootstrap_firewall.sh", 0700, 0},
    {"device_agent/init/c300x-native-agent", 0700, 0},
    {"device_agent/qml/Alarm.qml", 0644, 0},
    {"device_agent/qml/HomeAssistant.qml", 0644, 0},
    {"device_agent/qml/js/c300x_ha.js", 0644, 0},
    {"device_agent/qml/js/c300x_i18n.js", 0644, 0},
    {"device_agent/qml/js/c300x_memos.js", 0644, 0},
    {"device_agent/patches/common.sh", 0700, 1},
    {"device_agent/patches/display_qml.sh", 0700, 1},
    {"device_agent/patches/firewall.sh", 0700, 1},
    {"device_agent/patches/legacy_mqtt.sh", 0700, 1},
    {"device_agent/patches/audio_codec.sh", 0700, 1},
    {"device_agent/patches/device_routing.sh", 0700, 1},
    {"device_agent/bundle.json", 0600, 0},
};

#define C300X_AGENT_UPDATE_FILE_COUNT \
    (sizeof(C300X_AGENT_UPDATE_FILES) / sizeof(C300X_AGENT_UPDATE_FILES[0]))

static int c300x_agent_update_file_path(const char *path)
{
    for (size_t index = 0; index < C300X_AGENT_UPDATE_FILE_COUNT; index++) {
        if (strcmp(path, C300X_AGENT_UPDATE_FILES[index].path) == 0) {
            return 1;
        }
    }
    return 0;
}

static int c300x_agent_update_patch_path(const char *path)
{
    for (size_t index = 0; index < C300X_AGENT_UPDATE_FILE_COUNT; index++) {
        if (C300X_AGENT_UPDATE_FILES[index].optional && strcmp(path, C300X_AGENT_UPDATE_FILES[index].path) == 0) {
            return 1;
        }
    }
    return 0;
}

#endif
