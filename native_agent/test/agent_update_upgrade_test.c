/* Compile unchanged legacy/current updaters against temporary device paths. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/statvfs.h>
#include "../src/agent_update.h"
#include "../src/device_detect.h"

enum c300x_device_model c300x_device_model(void)
{
    return getenv("C100X_TEST_MODEL") ? C300X_DEVICE_MODEL_C100X : C300X_DEVICE_MODEL_C300X;
}

static char init_script[512], init_link[512], gui_wrapper[512];
static int remount_calls, activation_calls, activation_fails;

static int simulated_remount(const char *command)
{
    remount_calls++;
    assert(strcmp(command, "mount -o remount,rw / >/dev/null 2>&1") == 0
        || strcmp(command, "mount -o remount,ro / >/dev/null 2>&1") == 0);
    return 0;
}

/* External linkage keeps the same harness usable with older updater sources. */
int simulated_statvfs(const char *path, struct statvfs *info)
{
    assert(strcmp(path, "/") == 0);
    memset(info, 0, sizeof(*info));
    info->f_flag = ST_RDONLY;
    return 0;
}

#undef C300X_AGENT_INIT_SCRIPT
#undef C300X_AGENT_INIT_LINK
#define C300X_AGENT_INIT_SCRIPT init_script
#define C300X_AGENT_INIT_LINK init_link
#define C300X_AGENT_GUI_WRAPPER gui_wrapper
/* C300X_TEST_QT5=1: the station has the Qt 5 display of firmware 3.0.x. */
int c300x_device_display_is_qt5(void)
{
    const char *qt5 = getenv("C300X_TEST_QT5");
    return qt5 != NULL && strcmp(qt5, "1") == 0;
}

#define system simulated_remount
#define statvfs(path, info) simulated_statvfs(path, info)
#include "../src/agent_update.c"
#undef statvfs
#undef system

static int record_activation(const struct c300x_config *config, struct agent_update_change_summary *summary)
{
    (void)config;
    (void)summary;
    activation_calls++;
    return !activation_fails;
}

int main(int argc, char **argv)
{
    assert(argc == 4 || (argc == 5 && !strcmp(argv[4], "fail-activation")));
    struct c300x_config config = {0};
    struct agent_update_change_summary summary;
    char manifest[8192], installed_manifest[8192] = "{}", installed_path[C300X_MAX_PATH_LEN];
    int truncated = 0;
    assert(c300x_join_path(config.config_path, sizeof(config.config_path), argv[1], "config.json"));
    assert(c300x_join_path(init_script, sizeof(init_script), argv[1], "init-script"));
    assert(c300x_join_path(init_link, sizeof(init_link), argv[1], "init-link"));
    const char *wrapper = getenv("C300X_TEST_GUI_WRAPPER");
    if (wrapper != NULL) {
        assert(snprintf(gui_wrapper, sizeof(gui_wrapper), "%s", wrapper) < (int)sizeof(gui_wrapper));
    } else {
        assert(c300x_join_path(gui_wrapper, sizeof(gui_wrapper), argv[1], "BtClass_qws"));
    }
    assert(read_bounded_text_file(argv[2], manifest, sizeof(manifest), &truncated) && !truncated);
    assert(c300x_join_path(installed_path, sizeof(installed_path), argv[1], "bundle.json"));
    if (access(installed_path, F_OK) == 0) {
        assert(read_bounded_text_file(installed_path, installed_manifest, sizeof(installed_manifest), &truncated) && !truncated);
    }
    int expected = atoi(argv[3]);
    activation_fails = argc == 5;
    assert(apply_agent_update_files(&config, manifest, installed_manifest, &summary,
        record_activation) == expected);
    if (!expected) {
        assert(summary.changed_files == 0);
    }
    printf("{\"ok\":%s,\"changed_files\":%d,\"runtime_changed\":%s,\"qml_patch_changed\":%s,\"script_changed\":%s,\"manifest_changed\":%s,\"remount_calls\":%d,\"activation_calls\":%d}\n",
        expected ? "true" : "false", summary.changed_files,
        summary.runtime_changed ? "true" : "false", summary.qml_patch_changed ? "true" : "false",
        summary.script_changed ? "true" : "false", summary.manifest_changed ? "true" : "false",
        remount_calls, activation_calls);
    return 0;
}
