/* Only temporary-directory files are touched; no agent or system service runs. */
#include <assert.h>
#include <stdlib.h>
#include <sys/stat.h>

static int must_not_run_system_command(const char *unused)
{
    (void)unused;
    abort();
}

#define system must_not_run_system_command
#include "../src/agent_update.c"
#undef system

int main(int argc, char **argv)
{
    assert(argc == 2);
    struct c300x_config config = {0};
    struct agent_update_change_summary summary = {0};
    const char *bundle_path = "device_agent/qml/test.qml";
    char stage[C300X_MAX_PATH_LEN], target[C300X_MAX_PATH_LEN];
    char digest[65], manifest[1024], content[32];
    struct stat before, after;
    const char *invalid[] = {
        "/etc/passwd", "device_agent/../escape", "device_agent/qml/../../escape",
        "device_agent/qml/..", "device_agent/qml\\escape", "device_agent/scripts/unknown.sh"
    };
    assert(c300x_join_path(config.config_path, sizeof(config.config_path), argv[1], "config.json"));
    for (size_t i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++) {
        assert(!agent_update_stage_path(&config, invalid[i], stage, sizeof(stage)));
        assert(!agent_update_target_path(&config, invalid[i], target, sizeof(target)));
    }
    assert(agent_update_stage_path(&config, bundle_path, stage, sizeof(stage)));
    assert(agent_update_target_path(&config, bundle_path, target, sizeof(target)));
    assert(strncmp(stage, argv[1], strlen(argv[1])) == 0);
    assert(strncmp(target, argv[1], strlen(argv[1])) == 0);
    assert(apply_agent_update_file(&config, "{}", bundle_path, 0600, 1, &summary));
    assert(!apply_agent_update_file(&config, "{}", bundle_path, 0600, 0, &summary));
    assert(write_binary_chunk(stage, (const unsigned char *)"first", 5, 0, 0600));
    assert(!write_binary_chunk(stage, (const unsigned char *)"bad", 3, 4, 0600));
    assert(write_binary_chunk(stage, (const unsigned char *)"!", 1, 5, 0600));
    assert(c300x_sha256_file_hex(stage, digest, sizeof(digest)));
    assert(snprintf(manifest, sizeof(manifest), "{\"files\":[{\"path\":\"%s\",\"sha256\":\"%s\"}]}",
                    bundle_path, digest) < (int)sizeof(manifest));
    assert(apply_agent_update_file(&config, manifest, bundle_path, 0600, 0, &summary));
    assert(summary.changed_files == 1 && summary.qml_patch_changed);
    assert(stat(target, &before) == 0);
    assert((before.st_mode & 0777) == 0600);
    assert(read_bounded_text_file(target, content, sizeof(content), NULL));
    assert(strcmp(content, "first!") == 0);
    assert(apply_agent_update_file(&config, manifest, bundle_path, 0600, 0, &summary));
    assert(stat(target, &after) == 0);
    assert(before.st_ino == after.st_ino && summary.changed_files == 1);
    assert(write_binary_chunk(stage, (const unsigned char *)"changed", 7, 0, 0600));
    assert(!apply_agent_update_file(&config, manifest, bundle_path, 0600, 0, &summary));
    assert(read_bounded_text_file(target, content, sizeof(content), NULL));
    assert(strcmp(content, "first!") == 0);
    assert(unlink(stage) == 0);
    assert(!apply_agent_update_file(&config, manifest, bundle_path, 0600, 1, &summary));
    return 0;
}
