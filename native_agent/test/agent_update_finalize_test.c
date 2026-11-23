/* Real updater/files, temporary paths and injected syscalls; no device access. */
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>
#include "../src/agent_update.h"
#include "../src/file_io.h"
#include "../src/device_detect.h"

enum c300x_device_model c300x_device_model(void) { return C300X_DEVICE_MODEL_C300X; }

static char init_script[512], init_link[512], denied_backup[512];
static int fail_cleanup, cleanup_failures, root_writable_model;
static int rw_calls, ro_calls, fail_rw_at, fail_ro_at, remount_failures;
static int fail_rollback_rw, fail_rollback_ro;
static int persistent_ro_failure;
static int fail_root_query, root_queries, activation_calls;

static int simulated_statvfs(const char *path, struct statvfs *info)
{
    assert(!strcmp(path, "/"));
    root_queries++;
    /* Misleading errno must never select the HTTP error classification. */
    errno = EBUSY;
    if (fail_root_query) return -1;
    memset(info, 0, sizeof(*info));
    info->f_flag = root_writable_model ? 0 : ST_RDONLY;
    return 0;
}

static int simulated_remount(const char *command)
{
    errno = ENOENT;
    if (!strcmp(command, "mount -o remount,rw / >/dev/null 2>&1")) {
        if (++rw_calls == fail_rw_at) {
            remount_failures++;
            return 256;
        }
        root_writable_model = 1;
        return 0;
    }
    assert(!strcmp(command, "mount -o remount,ro / >/dev/null 2>&1"));
    if (++ro_calls == fail_ro_at || (persistent_ro_failure && fail_ro_at && ro_calls >= fail_ro_at)) {
        remount_failures++;
        return 256;
    }
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
#define statvfs(path, info) simulated_statvfs(path, info)
#define unlink injected_unlink
#include "../src/agent_update.c"
#undef statvfs
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

static void assert_previous(const struct c300x_config *config)
{
    char target[C300X_MAX_PATH_LEN], content[8192];
    struct stat info;
    for (size_t i = 0; i < C300X_AGENT_UPDATE_FILE_COUNT; i++) {
        const char *name = C300X_AGENT_UPDATE_FILES[i].path;
        assert(agent_update_target_path(config, name, target, sizeof(target)));
        assert(read_bounded_text_file(target, content, sizeof(content), NULL));
        int is_manifest = !strcmp(name, "device_agent/bundle.json");
        assert(!strcmp(content, is_manifest ? "old-manifest" : "old-payload"));
        assert(lstat(target, &info) == 0);
        assert((info.st_mode & 0777) == (is_manifest ? 0600 : 0640));
    }
    assert(agent_init_link_matches());
    assert(agent_update_target_path(config, "device_agent/qml/C300XEnergyDistribution.qml", target, sizeof(target)));
    assert(read_bounded_text_file(target, content, sizeof(content), NULL));
    assert(!strcmp(content, "old-payload"));
}

static int fail_activation(const struct c300x_config *config, struct agent_update_change_summary *summary)
{
    activation_calls++;
    (void)config;
    (void)summary;
    if (fail_rollback_rw) fail_rw_at = rw_calls + 1;
    if (fail_rollback_ro) fail_ro_at = ro_calls + 1;
    return 0;
}

static void assert_retry_preserves_backup(const struct c300x_config *config, const char *manifest, const char *path)
{
    struct agent_update_change_summary summary;
    struct stat before, after;
    char digest[65];
    assert(lstat(path, &before) == 0);
    assert(c300x_sha256_file_hex(path, digest, sizeof(digest)));
    fail_rw_at = fail_ro_at = 0;
    assert(!apply_agent_update_files(config, manifest, manifest, &summary, NULL));
    assert(summary.changed_files == 0);
    assert(summary.error == AGENT_UPDATE_ERROR_NONE);
    assert(lstat(path, &after) == 0 && before.st_ino == after.st_ino);
    assert(before.st_mode == after.st_mode && sha256_hex_matches(path, digest));
}

static void test_remount(const struct c300x_config *config, const char *manifest, const char *scenario)
{
    struct agent_update_change_summary summary;
    char backup[C300X_MAX_PATH_LEN];
    assert(agent_base_dir(config, backup, sizeof(backup)));
    size_t used = strlen(backup);
    assert(c300x_appendf(backup, sizeof(backup), &used, "/c300x-agent-native.update-backup"));
    if (!strcmp(scenario, "remount-finalize-rw-ro") || !strcmp(scenario, "remount-cleanup-ro")) {
        fail_ro_at = 3;
        if (!strcmp(scenario, "remount-finalize-rw-ro")) {
            fail_rw_at = 3;
        } else {
            fail_cleanup = 1;
            assert(strlen(backup) < sizeof(denied_backup));
            strcpy(denied_backup, backup);
        }
        assert(!apply_agent_update_files(config, manifest, "{}", &summary, NULL));
        assert(summary.error == AGENT_UPDATE_ROOT_READONLY_FAILED);
        assert(summary.changed_files > 0 && summary.manifest_changed);
        assert_committed(config, manifest);
        root_writable_model = 0; /* External recovery before retry. */
        fail_cleanup = 0;
        assert_retry_preserves_backup(config, manifest, backup);
        return;
    }
    if (!strcmp(scenario, "remount-link-rw") || !strcmp(scenario, "remount-link-ro")) {
        int rw_failure = !strcmp(scenario, "remount-link-rw");
        assert(chmod(init_script, 0700) == 0 && unlink(init_link) == 0);
        fail_rw_at = rw_failure;
        fail_ro_at = !rw_failure;
        memset(&summary, 0, sizeof(summary));
        assert(!repair_agent_init_link_after_update(&summary));
        assert(summary.changed_files == 0 && remount_failures == 1);
        assert(summary.error == (rw_failure ? AGENT_UPDATE_ERROR_NONE : AGENT_UPDATE_ROOT_READONLY_FAILED));
        assert(agent_init_link_matches() == !rw_failure);
        assert(root_writable_model == !rw_failure);
        fail_rw_at = fail_ro_at = 0;
        root_writable_model = 0; /* Explicit external recovery before retry. */
        assert(apply_agent_update_files(config, manifest, "{}", &summary, NULL));
        assert(!root_writable_model);
        assert_committed(config, manifest);
        return;
    }
    if (!strcmp(scenario, "remount-no-root-change")) {
        struct update_transaction *transaction = calloc(1, sizeof(*transaction));
        assert(transaction != NULL);
        memset(&summary, 0, sizeof(summary));
        transaction->summary = &summary;
        root_writable_model = 1;
        fail_ro_at = 1;
        assert(!update_finish_transaction(transaction, 0));
        assert(summary.error == AGENT_UPDATE_ROOT_READONLY_FAILED);
        assert(root_writable_model && rw_calls == 0);
        fail_ro_at = 0;
        assert(update_finish_transaction(transaction, 0));
        assert(!root_writable_model && rw_calls == 0);
        free(transaction);
        return;
    }
    if (!strcmp(scenario, "remount-prepare-rw")) fail_rw_at = 1;
    else if (!strcmp(scenario, "remount-prepare-ro")) fail_ro_at = 1;
    else if (!strcmp(scenario, "remount-install-rw")) fail_rw_at = 2;
    else if (!strcmp(scenario, "remount-install-ro")) fail_ro_at = 2;
    else if (!strcmp(scenario, "remount-finalize-rw")) fail_rw_at = 3;
    else if (!strcmp(scenario, "remount-finalize-ro")) {
        fail_ro_at = 3;
        persistent_ro_failure = 1;
    }
    else if (!strcmp(scenario, "remount-rollback-rw")) fail_rollback_rw = 1;
    else if (!strcmp(scenario, "remount-rollback-ro")) fail_rollback_ro = 1;
    else assert(0);
    assert(!apply_agent_update_files(config, manifest, "{}", &summary,
        fail_rollback_rw || fail_rollback_ro ? fail_activation : NULL));
    assert(remount_failures == 1);
    enum agent_update_error expected = !strcmp(scenario + strlen(scenario) - 3, "-ro")
        ? AGENT_UPDATE_ROOT_READONLY_FAILED : AGENT_UPDATE_ERROR_NONE;
    assert(summary.error == expected);
    assert(agent_update_error_status(summary.error) == 500);
    assert(strstr(agent_update_error_json(summary.error), expected
        ? "update_root_readonly_failed" : "update_apply_failed"));
    if (!strcmp(scenario, "remount-finalize-ro")) {
        assert(summary.manifest_changed && summary.changed_files > 0 && root_writable_model);
        assert_committed(config, manifest);
        int before_rw = rw_calls, before_ro = ro_calls;
        assert(!apply_agent_update_files(config, manifest, manifest, &summary, NULL));
        assert(summary.error == AGENT_UPDATE_ROOT_ALREADY_WRITABLE);
        assert(rw_calls == before_rw && ro_calls == before_ro && summary.changed_files == 0);
        assert(root_writable_model);
        assert_committed(config, manifest);
    } else if (!strcmp(scenario, "remount-finalize-rw") || fail_rollback_rw) {
        assert(summary.changed_files > 0 && !root_writable_model);
        if (!fail_rollback_rw) assert_committed(config, manifest);
        assert_retry_preserves_backup(config, manifest, backup);
        return;
    } else {
        assert_previous(config);
        assert(fail_rollback_ro ? summary.changed_files > 0 : summary.changed_files == 0);
        assert(root_writable_model == fail_rollback_ro);
    }
    fail_rw_at = fail_ro_at = 0;
    root_writable_model = 0; /* Explicit external recovery before retry. */
    assert(apply_agent_update_files(config, manifest, manifest, &summary, NULL));
    assert(!root_writable_model);
    assert_committed(config, manifest);
}

static void test_preflight(const struct c300x_config *config, const char *manifest, const char *scenario)
{
    struct agent_update_change_summary summary;
    char target[C300X_MAX_PATH_LEN], backup[C300X_MAX_PATH_LEN + 24];
    root_writable_model = !strcmp(scenario, "preflight-rw");
    fail_root_query = !strcmp(scenario, "preflight-unknown");
    assert(!apply_agent_update_files(config, manifest, "{}", &summary, fail_activation));
    assert(root_queries == 1 && rw_calls == 0 && ro_calls == 0 && summary.changed_files == 0 && activation_calls == 0);
    assert(summary.error == (root_writable_model ? AGENT_UPDATE_ROOT_ALREADY_WRITABLE : AGENT_UPDATE_ERROR_NONE));
    assert(agent_update_error_status(summary.error) == (root_writable_model ? 409 : 500));
    assert(strstr(agent_update_error_json(summary.error), root_writable_model
        ? "update_root_already_writable" : "update_apply_failed"));
    assert_previous(config);
    for (size_t i = 0; i < C300X_AGENT_UPDATE_FILE_COUNT; i++) {
        assert(agent_update_target_path(config, C300X_AGENT_UPDATE_FILES[i].path, target, sizeof(target)));
        assert(snprintf(backup, sizeof(backup), "%s.update-backup", target) < (int)sizeof(backup));
        assert(access(backup, F_OK) != 0 && errno == ENOENT);
    }
    assert(!apply_agent_update_files(config, manifest, "{}", NULL, NULL));
    assert(rw_calls == 0 && ro_calls == 0);
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    struct c300x_config config = {0};
    struct agent_update_change_summary summary;
    char manifest[8192];
    stage_bundle(&config, argv[1], manifest, sizeof(manifest));
    if (!strncmp(argv[2], "preflight-", 10)) {
        test_preflight(&config, manifest, argv[2]);
        return 0;
    }
    if (!strncmp(argv[2], "remount-", 8)) {
        test_remount(&config, manifest, argv[2]);
        return 0;
    }
    fail_cleanup = strcmp(argv[2], "control") != 0;
    if (fail_cleanup) {
        assert(c300x_join_path(denied_backup, sizeof(denied_backup), argv[1], argv[2]));
    }
    int applied = apply_agent_update_files(&config, manifest, "{}", &summary, NULL);
    assert(summary.error == AGENT_UPDATE_ERROR_NONE);
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
