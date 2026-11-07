/* Only temporary-directory files are touched; no agent or system service runs. */
#include <assert.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <errno.h>
#include <string.h>
#include "../src/agent_update.h"
#include "../src/file_io.h"

static char test_init_script[512], test_init_link[512];
static char fail_target[512];
static int activation_calls;

static int test_copy(const char *source, const char *target, mode_t mode)
{
    if (strcmp(target, fail_target) == 0) {
        errno = ENOSPC;
        return 0;
    }
    return copy_binary_file(source, target, mode);
}

static int test_copy_if_changed(const char *source, const char *target, mode_t mode, int *changed)
{
    if (strcmp(target, fail_target) == 0) {
        errno = ENOSPC;
        return 0;
    }
    return copy_binary_file_if_changed(source, target, mode, changed);
}

static int simulated_remount(const char *command)
{
    assert(strcmp(command, "mount -o remount,rw / >/dev/null 2>&1") == 0
        || strcmp(command, "mount -o remount,ro / >/dev/null 2>&1") == 0);
    return 0;
}

#undef C300X_AGENT_INIT_SCRIPT
#undef C300X_AGENT_INIT_LINK
#define C300X_AGENT_INIT_SCRIPT test_init_script
#define C300X_AGENT_INIT_LINK test_init_link
#define copy_binary_file test_copy
#define copy_binary_file_if_changed test_copy_if_changed
#define system simulated_remount
#include "../src/agent_update.c"
#undef system
#undef copy_binary_file
#undef copy_binary_file_if_changed

static const char *test_content(const char *path)
{
    return strcmp(path, "device_agent/init/c300x-native-agent") == 0
        ? "DEFAULT_AGENT_DIR=\"/home/bticino/cfg/extra/c300x-native-agent\"\n"
        : "new-bundle-file";
}

static int fail_activation_once(const struct c300x_config *config, struct agent_update_change_summary *summary)
{
    char manifest_path[C300X_MAX_PATH_LEN], content[64];
    (void)summary;
    assert(agent_bundle_manifest_path(config, manifest_path, sizeof(manifest_path)));
    assert(read_bounded_text_file(manifest_path, content, sizeof(content), NULL));
    assert(strcmp(content, "original") == 0);
    return ++activation_calls > 1;
}

static void assert_original_bundle(const struct c300x_config *config)
{
    char path[C300X_MAX_PATH_LEN], content[64], backup[C300X_MAX_PATH_LEN + 24];
    for (size_t i = 0; i < C300X_AGENT_UPDATE_FILE_COUNT; i++) {
        assert(agent_update_target_path(config, C300X_AGENT_UPDATE_FILES[i].path, path, sizeof(path)));
        assert(read_bounded_text_file(path, content, sizeof(content), NULL));
        assert(strcmp(content, "original") == 0);
        assert(snprintf(backup, sizeof(backup), "%s.update-backup", path) < (int)sizeof(backup));
        assert(access(backup, F_OK) != 0 && errno == ENOENT);
        struct stat info;
        assert(stat(path, &info) == 0 && (info.st_mode & 0777) == 0600);
    }
    ssize_t length = readlink(test_init_link, content, sizeof(content) - 1);
    assert(length > 0);
    content[length] = '\0';
    assert(strcmp(content, "old-agent") == 0);
}

static void rollback_test(const struct c300x_config *config, const char *manifest)
{
    char path[C300X_MAX_PATH_LEN];
    struct agent_update_change_summary summary;
    for (size_t i = 0; i < C300X_AGENT_UPDATE_FILE_COUNT; i++) {
        assert(agent_update_target_path(config, C300X_AGENT_UPDATE_FILES[i].path, path, sizeof(path)));
        assert(write_binary_chunk(path, (const unsigned char *)"original", 8, 0, 0600));
    }
    assert(symlink("old-agent", test_init_link) == 0);
    for (size_t i = 0; i < C300X_AGENT_UPDATE_FILE_COUNT; i++) {
        assert(agent_update_target_path(config, C300X_AGENT_UPDATE_FILES[i].path, fail_target, sizeof(fail_target)));
        assert(!apply_agent_update_files(config, manifest, "{}", &summary, NULL));
        assert(summary.changed_files == 0);
        assert_original_bundle(config);
    }
    fail_target[0] = '\0';
    assert(!apply_agent_update_files(config, manifest, "{}", &summary, fail_activation_once));
    assert(activation_calls == 2 && summary.changed_files == 0);
    assert_original_bundle(config);

    /* A newly introduced support file must disappear on a later failure. */
    assert(agent_update_target_path(config, C300X_AGENT_UPDATE_FILES[1].path, path, sizeof(path)));
    assert(unlink(path) == 0);
    assert(agent_bundle_manifest_path(config, fail_target, sizeof(fail_target)));
    assert(!apply_agent_update_files(config, manifest, "{}", &summary, NULL));
    assert(access(path, F_OK) != 0 && errno == ENOENT);
    fail_target[0] = '\0';
    assert(apply_agent_update_files(config, manifest, "{}", &summary, NULL));
    assert(summary.manifest_changed && summary.changed_files > 0);
    assert(agent_init_link_matches());
    assert(agent_bundle_manifest_path(config, path, sizeof(path)));
    char installed[8192];
    assert(read_bounded_text_file(path, installed, sizeof(installed), NULL));
    assert(strcmp(manifest, installed) == 0);

    /* Even an otherwise unchanged target cannot hide interrupted recovery data. */
    assert(agent_update_target_path(config, C300X_AGENT_UPDATE_FILES[1].path, path, sizeof(path)));
    char backup[C300X_MAX_PATH_LEN + 24];
    assert(snprintf(backup, sizeof(backup), "%s.update-backup", path) < (int)sizeof(backup));
    assert(link(path, backup) == 0);
    assert(!apply_agent_update_files(config, manifest, manifest, &summary, NULL));
    assert(summary.changed_files == 0);
    /* Successful removal also proves that the rejected update kept the backup. */
    assert(unlink(backup) == 0);
    assert(apply_agent_update_files(config, manifest, manifest, &summary, NULL));
    assert(summary.changed_files == 0);
}

static void whole_bundle_preflight_test(struct c300x_config *config)
{
    char manifest[8192], path[C300X_MAX_PATH_LEN], binary[C300X_MAX_PATH_LEN];
    char digest[65], installed[64];
    struct agent_update_change_summary summary;
    size_t used = 0;
    assert(agent_update_target_path(config, C300X_AGENT_UPDATE_FILES[0].path, binary, sizeof(binary)));
    assert(write_binary_chunk(binary, (const unsigned char *)"original", 8, 0, 0700));
    assert(c300x_appendf(manifest, sizeof(manifest), &used, "{\"files\":["));
    for (size_t i = 0; i + 1 < C300X_AGENT_UPDATE_FILE_COUNT; i++) {
        const char *name = C300X_AGENT_UPDATE_FILES[i].path;
        const char *content = test_content(name);
        assert(agent_update_stage_path(config, name, path, sizeof(path)));
        assert(write_binary_chunk(path, (const unsigned char *)content, strlen(content), 0, 0600));
        assert(c300x_sha256_file_hex(path, digest, sizeof(digest)));
        assert(c300x_appendf(manifest, sizeof(manifest), &used,
            "%s{\"path\":\"%s\",\"sha256\":\"%s\"}", i ? "," : "", name, digest));
    }
    assert(c300x_appendf(manifest, sizeof(manifest), &used, "]}"));
    assert(agent_update_stage_path(config, "device_agent/bundle.json", path, sizeof(path)));
    assert(write_binary_chunk(path, (const unsigned char *)manifest, strlen(manifest), 0, 0600));
    assert(validate_agent_update_files(config, manifest));
    for (size_t i = 0; i < C300X_AGENT_UPDATE_FILE_COUNT; i++) {
        const char *name = C300X_AGENT_UPDATE_FILES[i].path;
        const char *content = i + 1 == C300X_AGENT_UPDATE_FILE_COUNT ? manifest : test_content(name);
        assert(agent_update_stage_path(config, name, path, sizeof(path)));
        assert(unlink(path) == 0);
        assert(!apply_agent_update_files(config, manifest, "{}", &summary, NULL));
        assert(summary.changed_files == 0);
        assert(read_bounded_text_file(binary, installed, sizeof(installed), NULL));
        assert(strcmp(installed, "original") == 0);
        if (i + 1 < C300X_AGENT_UPDATE_FILE_COUNT) {
            assert(write_binary_chunk(path, (const unsigned char *)"corrupt", 7, 0, 0600));
            assert(!apply_agent_update_files(config, manifest, "{}", &summary, NULL));
            assert(summary.changed_files == 0);
            assert(read_bounded_text_file(binary, installed, sizeof(installed), NULL));
            assert(strcmp(installed, "original") == 0);
        }
        assert(write_binary_chunk(path, (const unsigned char *)content, strlen(content), 0, 0600));
    }
    assert(validate_agent_update_files(config, manifest));
    rollback_test(config, manifest);
}

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
    assert(c300x_join_path(test_init_script, sizeof(test_init_script), argv[1], "init-script"));
    assert(c300x_join_path(test_init_link, sizeof(test_init_link), argv[1], "init-link"));
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
    whole_bundle_preflight_test(&config);
    return 0;
}
