#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#include "agent_update.h"
#include "agent_update_paths.h"
#include "c300x_agent.h"
#include "file_io.h"
#include "json_util.h"
#include "sha256.h"
#include "string_util.h"
#include <errno.h>
#include <ctype.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <unistd.h>

#ifndef C300X_AGENT_GUI_WRAPPER
#define C300X_AGENT_GUI_WRAPPER "/home/bticino/bin/BtClass_qws"
#endif

#ifdef __arm__
#define C300X_UPDATE_STAT_STRUCT struct stat64
#else
#define C300X_UPDATE_STAT_STRUCT struct stat
#endif

static int update_lstat(const char *path, C300X_UPDATE_STAT_STRUCT *status)
{
#ifdef __arm__
    return (int)syscall(SYS_lstat64, path, status);
#else
    return lstat(path, status);
#endif
}

static int safe_agent_update_path(const char *path);
static int agent_update_target_path(
    const struct c300x_config *config,
    const char *bundle_path,
    char *out,
    size_t out_len
);
static int agent_update_manifest_field_changed(
    const char *installed_manifest,
    const char *staged_manifest,
    const char *field
);
static int agent_update_manifest_sha_for_path(
    const char *manifest,
    const char *bundle_path,
    char *sha256,
    size_t sha256_len
);
static int running_agent_binary_differs_from_update_manifest(const char *manifest);
static int apply_agent_update_file(
    const struct c300x_config *config,
    const char *manifest,
    const char *bundle_path,
    mode_t fallback_mode,
    int optional,
    struct agent_update_change_summary *summary
);
static int render_agent_init_script(
    const struct c300x_config *config,
    const char *source_path,
    const char *rendered_path
);
static int ensure_agent_init_link(void);
static int apply_agent_update_init_script(
    const struct c300x_config *config,
    const char *stage_path,
    int *changed
);
static int repair_agent_init_link_after_update(struct agent_update_change_summary *summary);
static int validate_agent_update_files(const struct c300x_config *config, const char *manifest);

struct update_backup {
    char target[C300X_MAX_PATH_LEN];
    char backup[C300X_MAX_PATH_LEN + 24];
    int existed;
};

struct update_transaction {
    struct update_backup files[C300X_AGENT_UPDATE_FILE_COUNT + 2];
    size_t count;
    int root_touched;
};

static int update_remount(int writable)
{
    int status = system(writable ? "mount -o remount,rw / >/dev/null 2>&1"
                                 : "mount -o remount,ro / >/dev/null 2>&1");
    if (status != 0) {
        fprintf(stderr, "Agent update root remount %s failed (status %d)\n", writable ? "rw" : "ro", status);
    }
    return status == 0;
}

static int update_backup_target(struct update_transaction *transaction, const char *target)
{
    C300X_UPDATE_STAT_STRUCT info;
    struct update_backup *file = &transaction->files[transaction->count];
    if (transaction->count >= sizeof(transaction->files) / sizeof(transaction->files[0])
        || snprintf(file->target, sizeof(file->target), "%s", target) >= (int)sizeof(file->target)
        || snprintf(file->backup, sizeof(file->backup), "%s.update-backup", target) >= (int)sizeof(file->backup)) {
        return 0;
    }
    /* Never overwrite recovery material left by an interrupted update. */
    if (update_lstat(file->backup, &info) == 0 || errno != ENOENT) {
        return 0;
    }
    if (update_lstat(target, &info) == 0) {
        if ((!S_ISREG(info.st_mode) && !S_ISLNK(info.st_mode)) || link(target, file->backup) != 0) {
            return 0;
        }
        file->existed = 1;
    } else if (errno != ENOENT) {
        return 0;
    }
    transaction->count++;
    return 1;
}

static int update_finish_transaction(struct update_transaction *transaction, int rollback)
{
    int ok = 1;
    if (transaction->root_touched && !update_remount(1)) {
        /* Do not consume recovery files when root writes are unavailable. */
        (void)update_remount(0);
        return 0;
    }
    for (size_t index = transaction->count; index > 0; index--) {
        struct update_backup *file = &transaction->files[index - 1];
        C300X_UPDATE_STAT_STRUCT target_info, backup_info;
        int unchanged = rollback && file->existed
            && update_lstat(file->target, &target_info) == 0 && update_lstat(file->backup, &backup_info) == 0
            && target_info.st_dev == backup_info.st_dev && target_info.st_ino == backup_info.st_ino;
        int result = rollback && file->existed && !unchanged
            ? rename(file->backup, file->target)
            : unlink(rollback && !file->existed ? file->target : file->backup);
        if (result != 0 && !(errno == ENOENT && !(rollback && file->existed))) {
            fprintf(stderr, "Agent update %s failed for %s; recovery files retained\n",
                rollback ? "rollback" : "backup cleanup", file->target);
            ok = 0;
        }
    }
    /* Also confirm read-only state on a retry with no remaining root changes. */
    if (!update_remount(0)) {
        ok = 0;
    }
    return ok;
}

static int update_remove_obsolete_display_source(
    const struct c300x_config *config,
    struct update_transaction *transaction,
    struct agent_update_change_summary *summary
)
{
    char base[C300X_MAX_PATH_LEN], directory[C300X_MAX_PATH_LEN];
    char target[C300X_MAX_PATH_LEN], backup[C300X_MAX_PATH_LEN + 24];
    C300X_UPDATE_STAT_STRUCT info;
    if (!agent_base_dir(config, base, sizeof(base))
        || !c300x_join_path(directory, sizeof(directory), base, "qml")
        || !c300x_join_path(target, sizeof(target), directory, "C300XEnergyDistribution.qml")
        || snprintf(backup, sizeof(backup), "%s.update-backup", target) >= (int)sizeof(backup)) {
        return 0;
    }
    if (update_lstat(directory, &info) != 0) {
        return errno == ENOENT;
    }
    if (!S_ISDIR(info.st_mode) || update_lstat(backup, &info) == 0 || errno != ENOENT) {
        return 0;
    }
    if (update_lstat(target, &info) != 0) {
        return errno == ENOENT;
    }
    /* Only this retired project file is owned here; never follow a symlink. */
    if (!S_ISREG(info.st_mode) || !update_backup_target(transaction, target)
        || unlink(target) != 0) {
        return 0;
    }
    if (summary != NULL) {
        summary->changed_files++;
        summary->qml_patch_changed = 1;
    }
    return 1;
}

static int update_prepare_transaction(const struct c300x_config *config, struct update_transaction *transaction)
{
    char target[C300X_MAX_PATH_LEN], stage[C300X_MAX_PATH_LEN];
    char backup[C300X_MAX_PATH_LEN + 24];
    C300X_UPDATE_STAT_STRUCT info;
    for (size_t index = 0; index < C300X_AGENT_UPDATE_FILE_COUNT; index++) {
        const char *name = C300X_AGENT_UPDATE_FILES[index].path;
        if (!agent_update_target_path(config, name, target, sizeof(target))
            || !agent_update_stage_path(config, name, stage, sizeof(stage))) {
            return 0;
        }
        if (snprintf(backup, sizeof(backup), "%s.update-backup", target) >= (int)sizeof(backup)
            || update_lstat(backup, &info) == 0 || errno != ENOENT) {
            return 0;
        }
        if (access(stage, F_OK) != 0 || file_content_matches(stage, target)) {
            continue;
        }
        if (strcmp(target, C300X_AGENT_INIT_SCRIPT) == 0) {
            transaction->root_touched = 1;
            if (!update_remount(1)) {
                return 0;
            }
        }
        if (!update_backup_target(transaction, target)) {
            return 0;
        }
    }
    if (snprintf(backup, sizeof(backup), "%s.update-backup", C300X_AGENT_INIT_LINK) >= (int)sizeof(backup)
        || update_lstat(backup, &info) == 0 || errno != ENOENT) {
        return 0;
    }
    if (!agent_init_link_matches()) {
        transaction->root_touched = 1;
        if (!update_remount(1) || !update_backup_target(transaction, C300X_AGENT_INIT_LINK)) {
            return 0;
        }
    }
    return !transaction->root_touched || update_remount(0);
}

int agent_base_dir(const struct c300x_config *config, char *out, size_t out_len)
{
    if (out_len == 0 || config == NULL || config->config_path[0] == '\0') {
        return 0;
    }
    if (strlen(config->config_path) >= out_len) {
        return 0;
    }
    c300x_copy_string(out, out_len, config->config_path);
    if (!path_parent_inplace(out)) {
        return 0;
    }
    return out[0] != '\0';
}

int agent_update_stage_dir(
    const struct c300x_config *config,
    char *out,
    size_t out_len
)
{
    char base[C300X_MAX_PATH_LEN];

    if (!agent_base_dir(config, base, sizeof(base))) {
        return 0;
    }
    return c300x_join_path(out, out_len, base, C300X_AGENT_UPDATE_STAGE);
}

int agent_bundle_manifest_path(
    const struct c300x_config *config,
    char *out,
    size_t out_len
)
{
    char base[C300X_MAX_PATH_LEN];

    if (!agent_base_dir(config, base, sizeof(base))) {
        return 0;
    }
    return c300x_join_path(out, out_len, base, C300X_AGENT_BUNDLE_MANIFEST);
}

int agent_update_stage_path(
    const struct c300x_config *config,
    const char *bundle_path,
    char *out,
    size_t out_len
)
{
    char stage_dir[C300X_MAX_PATH_LEN];

    if (!safe_agent_update_path(bundle_path) || !agent_update_stage_dir(config, stage_dir, sizeof(stage_dir))) {
        return 0;
    }
    return c300x_join_path(out, out_len, stage_dir, bundle_path);
}

int read_agent_bundle_metadata(
    const struct c300x_config *config,
    char *bundle_hash,
    size_t bundle_hash_len,
    char *agent_version,
    size_t agent_version_len,
    char *api_version,
    size_t api_version_len
)
{
    char manifest_path[C300X_MAX_PATH_LEN];
    char manifest[8192];
    int truncated = 0;

    if (bundle_hash_len > 0) {
        bundle_hash[0] = '\0';
    }
    if (agent_version_len > 0) {
        agent_version[0] = '\0';
    }
    if (api_version_len > 0) {
        api_version[0] = '\0';
    }
    if (!agent_bundle_manifest_path(config, manifest_path, sizeof(manifest_path))) {
        return 0;
    }
    if (!read_bounded_text_file(manifest_path, manifest, sizeof(manifest), &truncated) || truncated) {
        return 0;
    }
    c300x_json_string_field(manifest, "bundle_hash", bundle_hash, bundle_hash_len);
    c300x_json_string_field(manifest, "agent_version", agent_version, agent_version_len);
    if (agent_version_len > 0 && agent_version[0] == '\0') {
        c300x_json_string_field(manifest, "version", agent_version, agent_version_len);
    }
    c300x_json_string_field(manifest, "api_version", api_version, api_version_len);
    return bundle_hash[0] != '\0' || agent_version[0] != '\0' || api_version[0] != '\0';
}

int agent_init_link_matches(void)
{
    char current[C300X_MAX_PATH_LEN];
    char resolved[PATH_MAX];
    ssize_t len = readlink(C300X_AGENT_INIT_LINK, current, sizeof(current) - 1);

    if (len < 0) {
        return 0;
    }
    current[len] = '\0';
    if (strcmp(current, C300X_AGENT_INIT_SCRIPT) == 0) {
        return 1;
    }
    if (realpath(C300X_AGENT_INIT_LINK, resolved) == NULL) {
        return 0;
    }
    return strcmp(resolved, C300X_AGENT_INIT_SCRIPT) == 0;
}

static int update_has_qt5_recovery(const char *manifest)
{
    const char *end = manifest + strlen(manifest), *p = manifest;
    unsigned found = 0;
    int version = 0;
    if (!c300x_json_object_valid(manifest)) return 0;
    p += strspn(p, " \t\r\n") + 1;
    /* Enumerate top-level members with the shared JSON parser: duplicates or
     * nested declarations must not grant a recovery capability. */
    while (*(p += strspn(p, " \t\r\n")) != '}') {
        char key[128];
        if (!c300x_json_decode_string(p, end, key, sizeof(key), &p)) return 0;
        if (!strcmp(key, "qt5_recovery_version") && ++found > 1) return 0;
        p += strspn(p, " \t\r\n") + 1;
        p = c300x_json_skip_value(p, end);
        if (p == NULL) return 0;
        p += strspn(p, " \t\r\n");
        if (*p == ',') p++;
    }
    return found == 1
        && c300x_json_int_field_checked(manifest, "qt5_recovery_version", &version) == 1
        && version == C300X_AGENT_QT5_RECOVERY_VERSION;
}

static int update_path_matches_environment(const char *name, const char *path)
{
    const char *value = getenv(name);
    return value == NULL || *value == '\0' || strcmp(value, path) == 0;
}

static int update_display_recovery_safe(const struct c300x_config *config, const char *manifest)
{
    static const char *const artifacts[] = {
        "display-qt5.rcc", "c300x-qrc-overlay.so", "display-qt5.rcc.failed"
    };
    static const char *const overrides[] = {"C300X_QML_QT5_RCC", "C300X_QML_QT5_OVERLAY_LIB"};
    char base[C300X_MAX_PATH_LEN], path[C300X_MAX_PATH_LEN];
    C300X_UPDATE_STAT_STRUCT info;
    /* Capability describes the complete target bundle (runtime and scripts),
     * not a device model. A capable update retains recovery even if state is
     * unknown or quarantined. Older bundles require verified full removal. */
    if (update_has_qt5_recovery(manifest)) return 1;
    if (!agent_base_dir(config, base, sizeof(base))
        || update_lstat(base, &info) != 0 || !S_ISDIR(info.st_mode)
        || !update_path_matches_environment("C300X_AGENT_DIR", base)
        || !update_path_matches_environment("C300X_QML_GUI_WRAPPER", C300X_AGENT_GUI_WRAPPER)) return 0;
    for (size_t i = 0; i < sizeof(artifacts) / sizeof(artifacts[0]); i++) {
        if (!c300x_join_path(path, sizeof(path), base, artifacts[i])
            || (i < 2 && !update_path_matches_environment(overrides[i], path))
            || update_lstat(path, &info) == 0 || errno != ENOENT) return 0;
    }
    /* Missing, nonregular, unreadable or modified wrapper is not proof of
     * removal. These are original artifact hashes, never model detection. */
    if (update_lstat(C300X_AGENT_GUI_WRAPPER, &info) != 0
        || !S_ISREG(info.st_mode) || !(info.st_mode & 0111)
        || info.st_size <= 0 || info.st_size > 16384) return 0;
    return sha256_hex_matches(C300X_AGENT_GUI_WRAPPER,
               "852a5b0f0755a738e4e25127cd10b903fbf9c2ebdb4109872d4e1d0aac13c59c")
        || sha256_hex_matches(C300X_AGENT_GUI_WRAPPER,
               "903eeca1eb142238f32345c6837125c29dcb2a5b63fb4eda935a82e70104229f");
}

int apply_agent_update_files(
    const struct c300x_config *config,
    const char *manifest,
    const char *installed_manifest,
    struct agent_update_change_summary *summary,
    int (*activate)(const struct c300x_config *, struct agent_update_change_summary *)
)
{
    struct update_transaction *transaction;
    int activation_attempted = 0;
    if (summary != NULL) {
        memset(summary, 0, sizeof(*summary));
    }
    /* Never install an earlier file from an incomplete or corrupt staged bundle. */
    if (!validate_agent_update_files(config, manifest)) {
        return 0;
    }
    if (!update_display_recovery_safe(config, manifest)) {
        if (summary != NULL) summary->qt5_recovery_required = 1;
        fprintf(stderr, "qt5_recovery_required: target lacks Qt5 recovery; verify complete display removal before downgrade\n");
        return 0;
    }
    transaction = calloc(1, sizeof(*transaction));
    if (transaction == NULL) {
        return 0;
    }
    if (!update_prepare_transaction(config, transaction)) {
        (void)update_finish_transaction(transaction, 0);
        free(transaction);
        return 0;
    }
    if (summary != NULL) {
        summary->runtime_changed = agent_update_manifest_field_changed(installed_manifest, manifest, "runtime_hash")
            || running_agent_binary_differs_from_update_manifest(manifest);
        summary->qml_patch_changed = agent_update_manifest_field_changed(
            installed_manifest,
            manifest,
            "qml_patch_hash"
        );
        summary->script_changed = agent_update_manifest_field_changed(
            installed_manifest,
            manifest,
            "script_hash"
        );
        summary->firewall_patch_changed = agent_update_manifest_field_changed(
            installed_manifest,
            manifest,
            "firewall_patch_hash"
        );
        summary->ipv6_firewall_patch_changed = agent_update_manifest_field_changed(
            installed_manifest,
            manifest,
            "ipv6_firewall_patch_hash"
        );
        summary->config_schema_changed = agent_update_manifest_field_changed(
            installed_manifest,
            manifest,
            "config_schema_hash"
        );
    }
    if (!update_remove_obsolete_display_source(config, transaction, summary)) {
        goto rollback;
    }
    for (size_t index = 0; index < C300X_AGENT_UPDATE_FILE_COUNT; index++) {
        if (strcmp(C300X_AGENT_UPDATE_FILES[index].path, "device_agent/bundle.json") == 0) {
            if (!repair_agent_init_link_after_update(summary)) {
                goto rollback;
            }
            if (activate != NULL) {
                activation_attempted = 1;
                if (!activate(config, summary)) {
                    goto rollback;
                }
            }
        }
        if (
            !apply_agent_update_file(
                config,
                manifest,
                C300X_AGENT_UPDATE_FILES[index].path,
                C300X_AGENT_UPDATE_FILES[index].mode,
                C300X_AGENT_UPDATE_FILES[index].optional,
                summary
            )
        ) {
            goto rollback;
        }
    }
    /* Installed files stay committed: cleanup may already have deleted backups.
     * Report finalization failure without rollback or clearing the summary. */
    int finalized = update_finish_transaction(transaction, 0);
    free(transaction);
    return finalized;

rollback:
    if (update_finish_transaction(transaction, 1)) {
        if (activation_attempted && !activate(config, summary)) {
            fprintf(stderr, "Agent update: restoring previous firewall settings failed\n");
        }
        if (summary != NULL) {
            memset(summary, 0, sizeof(*summary));
        }
    }
    free(transaction);
    return 0;
}

static int validate_agent_update_files(const struct c300x_config *config, const char *manifest)
{
    char stage[C300X_MAX_PATH_LEN];
    char target[C300X_MAX_PATH_LEN];
    char sha256[65];
    for (size_t index = 0; index < C300X_AGENT_UPDATE_FILE_COUNT; index++) {
        const struct c300x_agent_update_file *file = &C300X_AGENT_UPDATE_FILES[index];
        if (!agent_update_stage_path(config, file->path, stage, sizeof(stage))
            || !agent_update_target_path(config, file->path, target, sizeof(target))) {
            return 0;
        }
        int has_hash = agent_update_manifest_sha_for_path(manifest, file->path, sha256, sizeof(sha256));
        if (access(stage, F_OK) != 0) {
            if (errno == ENOENT && file->optional && !has_hash) {
                continue;
            }
            return 0;
        }
        if (strcmp(file->path, "device_agent/bundle.json") != 0
            && (!has_hash || !sha256_hex_matches(stage, sha256))) {
            return 0;
        }
        if (strcmp(file->path, "device_agent/init/c300x-native-agent") == 0) {
            char rendered[C300X_MAX_PATH_LEN + 16];
            if (snprintf(rendered, sizeof(rendered), "%s.rendered", stage) >= (int)sizeof(rendered)) {
                return 0;
            }
            int valid = render_agent_init_script(config, stage, rendered);
            (void)unlink(rendered);
            if (!valid) {
                return 0;
            }
        }
    }
    return 1;
}

static int safe_agent_update_path(const char *path)
{
    size_t len;
    const char *prefix = "device_agent/";

    if (path == NULL || path[0] == '\0' || path[0] == '/' || strstr(path, "\\") != NULL) {
        return 0;
    }
    len = strlen(path);
    if (len >= C300X_MAX_PATH_LEN || strncmp(path, prefix, strlen(prefix)) != 0) {
        return 0;
    }
    if (strstr(path, "/../") != NULL || strstr(path, "../") == path || strstr(path, "/..") == path + len - 3) {
        return 0;
    }
    if (c300x_agent_update_file_path(path) || strncmp(path, "device_agent/qml/", strlen("device_agent/qml/")) == 0) {
        return 1;
    }
    return 0;
}

static int agent_update_target_path(
    const struct c300x_config *config,
    const char *bundle_path,
    char *out,
    size_t out_len
)
{
    char base[C300X_MAX_PATH_LEN];
    const char *relative_target = NULL;

    if (!safe_agent_update_path(bundle_path) || !agent_base_dir(config, base, sizeof(base))) {
        return 0;
    }
    if (strcmp(bundle_path, "device_agent/armhf/c300x-agent-native") == 0) {
        relative_target = "c300x-agent-native";
    } else if (strcmp(bundle_path, "device_agent/scripts/qml_patch.sh") == 0) {
        relative_target = "qml_patch.sh";
    } else if (strcmp(bundle_path, "device_agent/scripts/remove_agent.sh") == 0) {
        relative_target = "remove_agent.sh";
    } else if (strcmp(bundle_path, "device_agent/scripts/bootstrap_firewall.sh") == 0) {
        relative_target = "bootstrap_firewall.sh";
    } else if (strcmp(bundle_path, "device_agent/init/c300x-native-agent") == 0) {
        if (strlen(C300X_AGENT_INIT_SCRIPT) >= out_len) {
            return 0;
        }
        c300x_copy_string(out, out_len, C300X_AGENT_INIT_SCRIPT);
        return 1;
    } else if (strcmp(bundle_path, "device_agent/bundle.json") == 0) {
        relative_target = C300X_AGENT_BUNDLE_MANIFEST;
    } else if (
        c300x_agent_update_patch_path(bundle_path)
        || strncmp(bundle_path, "device_agent/qml/", strlen("device_agent/qml/")) == 0
    ) {
        relative_target = bundle_path + strlen("device_agent/");
    }
    if (relative_target == NULL) {
        return 0;
    }
    return c300x_join_path(out, out_len, base, relative_target);
}

static int agent_update_manifest_field_changed(
    const char *installed_manifest,
    const char *staged_manifest,
    const char *field
)
{
    char installed_value[C300X_AGENT_BUNDLE_HASH_LEN];
    char staged_value[C300X_AGENT_BUNDLE_HASH_LEN];

    c300x_json_string_field(staged_manifest, field, staged_value, sizeof(staged_value));
    if (staged_value[0] == '\0') {
        return 0;
    }
    if (installed_manifest == NULL || installed_manifest[0] == '\0') {
        return 1;
    }
    c300x_json_string_field(installed_manifest, field, installed_value, sizeof(installed_value));
    return !constant_time_equal(
        installed_value,
        strlen(installed_value),
        staged_value
    );
}

static int agent_update_manifest_sha_for_path(
    const char *manifest,
    const char *bundle_path,
    char *sha256,
    size_t sha256_len
)
{
    const char *entry;
    const char *end = manifest + strlen(manifest);
    if (sha256_len > 0) { sha256[0] = '\0'; }
    if (!c300x_json_find_member(manifest, end, "files", &entry) || *entry++ != '[') {
        return 0;
    }
    while (entry < end) {
        while (entry < end && isspace((unsigned char)*entry)) { entry++; }
        if (entry >= end || *entry != '{') { return 0; }
        const char *after = c300x_json_skip_value(entry, end);
        const char *value;
        char path[C300X_MAX_PATH_LEN];
        if (after == NULL) { return 0; }
        if (c300x_json_find_member(entry, after, "path", &value)
            && c300x_json_decode_string(value, after, path, sizeof(path), NULL)
            && strcmp(path, bundle_path) == 0) {
            return c300x_json_find_member(entry, after, "sha256", &value)
                && c300x_json_decode_string(value, after, sha256, sha256_len, NULL)
                && sha256[0] != '\0';
        }
        entry = after;
        while (entry < end && isspace((unsigned char)*entry)) { entry++; }
        if (entry >= end || *entry++ != ',') { return 0; }
    }
    return 0;
}

static int running_agent_binary_differs_from_update_manifest(const char *manifest)
{
    char expected_sha256[65], running_sha256[65];
    return agent_update_manifest_sha_for_path(manifest, "device_agent/armhf/c300x-agent-native", expected_sha256, sizeof(expected_sha256))
        && c300x_sha256_file_hex("/proc/self/exe", running_sha256, sizeof(running_sha256))
        && !constant_time_equal(running_sha256, strlen(running_sha256), expected_sha256);
}

static int apply_agent_update_file(
    const struct c300x_config *config,
    const char *manifest,
    const char *bundle_path,
    mode_t fallback_mode,
    int optional,
    struct agent_update_change_summary *summary
)
{
    char stage_path[C300X_MAX_PATH_LEN];
    char target_path[C300X_MAX_PATH_LEN];
    char sha256[65];
    int changed = 0;

    if (
        !agent_update_stage_path(config, bundle_path, stage_path, sizeof(stage_path))
        || !agent_update_target_path(config, bundle_path, target_path, sizeof(target_path))
    ) {
        return 0;
    }
    if (access(stage_path, F_OK) != 0) {
        return optional && !agent_update_manifest_sha_for_path(manifest, bundle_path, sha256, sizeof(sha256));
    }
    if (
        strcmp(bundle_path, "device_agent/bundle.json") != 0
        && (
            !agent_update_manifest_sha_for_path(manifest, bundle_path, sha256, sizeof(sha256))
            || !sha256_hex_matches(stage_path, sha256)
        )
    ) {
        return 0;
    }
    if (strcmp(bundle_path, "device_agent/init/c300x-native-agent") == 0) {
        if (!apply_agent_update_init_script(config, stage_path, &changed)) {
            return 0;
        }
        if (changed && summary != NULL) {
            summary->changed_files++;
            summary->script_changed = 1;
        }
        return 1;
    }
    if (!copy_binary_file_if_changed(stage_path, target_path, fallback_mode, &changed)) {
        return 0;
    }
    if (changed && summary != NULL) {
        summary->changed_files++;
        if (strcmp(bundle_path, "device_agent/armhf/c300x-agent-native") == 0) {
            summary->runtime_changed = 1;
        } else if (strcmp(bundle_path, "device_agent/scripts/qml_patch.sh") == 0) {
            summary->script_changed = 1;
            summary->qml_patch_changed = 1;
        } else if (strcmp(bundle_path, "device_agent/scripts/remove_agent.sh") == 0) {
            summary->script_changed = 1;
        } else if (strcmp(bundle_path, "device_agent/init/c300x-native-agent") == 0) {
            summary->script_changed = 1;
        } else if (strcmp(bundle_path, "device_agent/bundle.json") == 0) {
            summary->manifest_changed = 1;
        } else if (c300x_agent_update_patch_path(bundle_path)) {
            summary->script_changed = 1;
        } else if (strncmp(bundle_path, "device_agent/qml/", strlen("device_agent/qml/")) == 0) {
            summary->qml_patch_changed = 1;
        }
    }
    return 1;
}

static int render_agent_init_script(
    const struct c300x_config *config,
    const char *source_path,
    const char *rendered_path
)
{
    struct render_init_workspace {
        char source[8192];
        char rendered[8192];
    };
    struct render_init_workspace *workspace = calloc(1, sizeof(*workspace));
    char base[C300X_MAX_PATH_LEN];
    const char *needle = "DEFAULT_AGENT_DIR=\"/home/bticino/cfg/extra/c300x-native-agent\"";
    const char *found;
    int truncated = 0;
    size_t prefix_len;
    size_t used = 0;

    if (workspace == NULL) {
        return 0;
    }
    if (
        !agent_base_dir(config, base, sizeof(base))
        || !read_bounded_text_file(source_path, workspace->source, sizeof(workspace->source), &truncated)
        || truncated
    ) {
        free(workspace);
        return 0;
    }
    found = strstr(workspace->source, needle);
    if (found == NULL) {
        free(workspace);
        return 0;
    }
    prefix_len = (size_t)(found - workspace->source);
    if (!c300x_appendf(
        workspace->rendered,
        sizeof(workspace->rendered),
        &used,
        "%.*sDEFAULT_AGENT_DIR=\"%s\"%s",
        (int)prefix_len,
        workspace->source,
        base,
        found + strlen(needle)
    )) {
        free(workspace);
        return 0;
    }
    int ok = write_binary_chunk(
        rendered_path,
        (const unsigned char *)workspace->rendered,
        strlen(workspace->rendered),
        0,
        0700
    );
    free(workspace);
    return ok;
}

static int ensure_agent_init_link(void)
{
    C300X_UPDATE_STAT_STRUCT info;
    if (agent_init_link_matches()) {
        return 1;
    }
    /* The update transaction has backed up any invalid regular file or link. */
    if (update_lstat(C300X_AGENT_INIT_LINK, &info) == 0) {
        if ((!S_ISREG(info.st_mode) && !S_ISLNK(info.st_mode))
            || unlink(C300X_AGENT_INIT_LINK) != 0) {
            return 0;
        }
    } else if (errno != ENOENT) {
        return 0;
    }
    return symlink(C300X_AGENT_INIT_SCRIPT, C300X_AGENT_INIT_LINK) == 0;
}

static int apply_agent_update_init_script(
    const struct c300x_config *config,
    const char *stage_path,
    int *changed
)
{
    char rendered_path[C300X_MAX_PATH_LEN + 16];
    int content_changed;
    int link_changed;

    if (changed != NULL) {
        *changed = 0;
    }
    if (snprintf(rendered_path, sizeof(rendered_path), "%s.rendered", stage_path) >= (int)sizeof(rendered_path)) {
        return 0;
    }
    if (!render_agent_init_script(config, stage_path, rendered_path)) {
        (void)unlink(rendered_path);
        return 0;
    }
    content_changed = !file_content_matches(rendered_path, C300X_AGENT_INIT_SCRIPT);
    link_changed = !agent_init_link_matches();
    if (!content_changed && !link_changed) {
        (void)unlink(rendered_path);
        return 1;
    }
    int ok = update_remount(1)
        && (!content_changed || copy_binary_file(rendered_path, C300X_AGENT_INIT_SCRIPT, 0700))
        && ensure_agent_init_link();
    int readonly_ok = update_remount(0);
    (void)unlink(rendered_path);
    if (!ok || !readonly_ok) {
        return 0;
    }
    if (changed != NULL) {
        *changed = 1;
    }
    return 1;
}

static int repair_agent_init_link_after_update(struct agent_update_change_summary *summary)
{
    if (agent_init_link_matches()) {
        return 1;
    }
    if (access(C300X_AGENT_INIT_SCRIPT, X_OK) != 0) {
        return 1;
    }
    int ok = update_remount(1) && ensure_agent_init_link();
    int readonly_ok = update_remount(0);
    if (!ok || !readonly_ok) {
        return 0;
    }
    if (summary != NULL) {
        summary->changed_files++;
        summary->script_changed = 1;
    }
    return 1;
}
