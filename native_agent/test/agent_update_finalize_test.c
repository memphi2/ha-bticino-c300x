/* Real updater/files, temporary paths and injected syscalls; no device access. */
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "../src/agent_update.h"
#include "../src/file_io.h"

static char init_script[512], init_link[512], denied_backup[512];
static int fail_cleanup, cleanup_failures, root_writable_model;

static int simulated_remount(const char *command)
{
    if (!strcmp(command, "mount -o remount,rw / >/dev/null 2>&1")) {
        root_writable_model = 1;
        return 0;
    }
    assert(!strcmp(command, "mount -o remount,ro / >/dev/null 2>&1"));
    root_writable_model = 0;
    return 0;
}

static int injected_unlink(const char *path)
{
    if (fail_cleanup && !strcmp(path, denied_backup)) {
        cleanup_failures++;
        errno = EACCES;
        return -1;
    }
    return unlink(path);
}

#undef C300X_AGENT_INIT_SCRIPT
#undef C300X_AGENT_INIT_LINK
#define C300X_AGENT_INIT_SCRIPT init_script
#define C300X_AGENT_INIT_LINK init_link
#define system simulated_remount
#define unlink injected_unlink
#include "../src/agent_update.c"
#undef system
#undef unlink

static void stage_bundle(struct c300x_config *config, const char *base, char *manifest, size_t capacity)
{
    char stage[C300X_MAX_PATH_LEN], target[C300X_MAX_PATH_LEN], digest[65];
    size_t used = 0;
    assert(c300x_join_path(config->config_path, sizeof(config->config_path), base, "config.json"));
    assert(c300x_join_path(init_script, sizeof(init_script), base, "init-script"));
    assert(c300x_join_path(init_link, sizeof(init_link), base, "init-link"));
    assert(c300x_appendf(manifest, capacity, &used, "{\"files\":["));
    for (size_t i = 0; i + 1 < C300X_AGENT_UPDATE_FILE_COUNT; i++) {
        const char *name = C300X_AGENT_UPDATE_FILES[i].path;
        const char *content = !strcmp(name, "device_agent/init/c300x-native-agent")
            ? "DEFAULT_AGENT_DIR=\"/home/bticino/cfg/extra/c300x-native-agent\"\n" : "new-payload";
        assert(agent_update_stage_path(config, name, stage, sizeof(stage)));
        assert(agent_update_target_path(config, name, target, sizeof(target)));
        assert(write_binary_chunk(stage, (const unsigned char *)content, strlen(content), 0, 0600));
        assert(write_binary_chunk(target, (const unsigned char *)"old-payload", 11, 0, 0640));
        assert(c300x_sha256_file_hex(stage, digest, sizeof(digest)));
        assert(c300x_appendf(manifest, capacity, &used,
            "%s{\"path\":\"%s\",\"sha256\":\"%s\"}", i ? "," : "", name, digest));
    }
    assert(c300x_appendf(manifest, capacity, &used, "]}"));
    assert(agent_update_stage_path(config, "device_agent/bundle.json", stage, sizeof(stage)));
    assert(agent_bundle_manifest_path(config, target, sizeof(target)));
    assert(write_binary_chunk(stage, (const unsigned char *)manifest, strlen(manifest), 0, 0600));
    assert(write_binary_chunk(target, (const unsigned char *)"old-manifest", 12, 0, 0600));
    assert(symlink(init_script, init_link) == 0);
    assert(agent_update_target_path(config, "device_agent/qml/C300XEnergyDistribution.qml", target, sizeof(target)));
    assert(write_binary_chunk(target, (const unsigned char *)"old-payload", 11, 0, 0640));
}

static void assert_committed(const struct c300x_config *config, const char *manifest)
{
    char target[C300X_MAX_PATH_LEN], content[8192], expected[1024], base[C300X_MAX_PATH_LEN];
    assert(agent_base_dir(config, base, sizeof(base)));
    assert(snprintf(expected, sizeof(expected), "DEFAULT_AGENT_DIR=\"%s\"", base) < (int)sizeof(expected));
    for (size_t i = 0; i < C300X_AGENT_UPDATE_FILE_COUNT; i++) {
        const char *name = C300X_AGENT_UPDATE_FILES[i].path;
        assert(agent_update_target_path(config, name, target, sizeof(target)));
        assert(read_bounded_text_file(target, content, sizeof(content), NULL));
        const char *wanted = !strcmp(name, "device_agent/init/c300x-native-agent") ? expected
            : !strcmp(name, "device_agent/bundle.json") ? manifest : "new-payload";
        assert(!strcmp(content, wanted));
    }
    assert(agent_init_link_matches());
    assert(agent_update_target_path(config, "device_agent/qml/C300XEnergyDistribution.qml", target, sizeof(target)));
    assert(access(target, F_OK) != 0 && errno == ENOENT);
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    struct c300x_config config = {0};
    struct agent_update_change_summary summary;
    char manifest[8192];
    stage_bundle(&config, argv[1], manifest, sizeof(manifest));
    fail_cleanup = strcmp(argv[2], "control") != 0;
    if (fail_cleanup) {
        assert(c300x_join_path(denied_backup, sizeof(denied_backup), argv[1], argv[2]));
    }
    int applied = apply_agent_update_files(&config, manifest, "{}", &summary, NULL);
    assert(applied == !fail_cleanup);
    assert(summary.manifest_changed && summary.changed_files > 0);
    assert(!root_writable_model);
    assert_committed(&config, manifest);
    if (fail_cleanup) {
        char digest[65];
        struct stat before, after;
        assert(cleanup_failures == 1);
        assert(lstat(denied_backup, &before) == 0);
        assert(c300x_sha256_file_hex(denied_backup, digest, sizeof(digest)));
        fail_cleanup = 0;
        /* Removing the fault is not authorization to discard old recovery data. */
        assert(!apply_agent_update_files(&config, manifest, manifest, &summary, NULL));
        assert(summary.changed_files == 0);
        assert(lstat(denied_backup, &after) == 0 && before.st_ino == after.st_ino);
        assert((before.st_mode & 0777) == (after.st_mode & 0777));
        assert(sha256_hex_matches(denied_backup, digest));
        assert_committed(&config, manifest);
    } else {
        assert(apply_agent_update_files(&config, manifest, manifest, &summary, NULL));
        assert(summary.changed_files == 0);
    }
    return 0;
}
