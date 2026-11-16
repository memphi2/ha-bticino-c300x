/* Compile unchanged legacy/current updaters against temporary device paths. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../src/agent_update.h"

static char init_script[512], init_link[512];

static int simulated_remount(const char *command)
{
    assert(strcmp(command, "mount -o remount,rw / >/dev/null 2>&1") == 0
        || strcmp(command, "mount -o remount,ro / >/dev/null 2>&1") == 0);
    return 0;
}

#undef C300X_AGENT_INIT_SCRIPT
#undef C300X_AGENT_INIT_LINK
#define C300X_AGENT_INIT_SCRIPT init_script
#define C300X_AGENT_INIT_LINK init_link
#define system simulated_remount
#include "../src/agent_update.c"
#undef system

int main(int argc, char **argv)
{
    assert(argc == 4);
    struct c300x_config config = {0};
    struct agent_update_change_summary summary;
    char manifest[8192];
    int truncated = 0;
    assert(c300x_join_path(config.config_path, sizeof(config.config_path), argv[1], "config.json"));
    assert(c300x_join_path(init_script, sizeof(init_script), argv[1], "init-script"));
    assert(c300x_join_path(init_link, sizeof(init_link), argv[1], "init-link"));
    assert(read_bounded_text_file(argv[2], manifest, sizeof(manifest), &truncated) && !truncated);
    int expected = atoi(argv[3]);
    assert(apply_agent_update_files(&config, manifest, "{}", &summary, NULL) == expected);
    if (!expected) {
        assert(summary.changed_files == 0);
    }
    return 0;
}
