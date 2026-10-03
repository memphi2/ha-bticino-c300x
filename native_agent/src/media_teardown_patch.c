#define _POSIX_C_SOURCE 200809L

#include "media_teardown_patch.h"

#include "c300x_agent.h"
#include "device_patch_io.h"
#include "string_util.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define C300X_MEDIA_TEARDOWN_TARGET_DIR "/home/bticino/bin"
#define C300X_MEDIA_TEARDOWN_BACKUP_DIR \
    "/home/bticino/cfg/extra/c300x-device-file-backups/original/home/bticino/bin"

#define C300X_MEDIA_TEARDOWN_TARGET_MASK "??_??_?????"

static const unsigned char MEDIA_TEARDOWN_WRITE[] = {0x40, 0x0d, 0x03};
static const struct c300x_patch_write MEDIA_TEARDOWN_WRITES[] = {
    {0, MEDIA_TEARDOWN_WRITE, sizeof(MEDIA_TEARDOWN_WRITE)},
};

#define C300X_MEDIA_TEARDOWN_STOCK_RANGE_SHA256 \
    "ebcdb6c80e93af3a75a7ea485ab65763ab7f2bf7a6e4ed1623640f0d6a2b050f"
#define C300X_MEDIA_TEARDOWN_PATCHED_RANGE_SHA256 \
    "347e4e96ea7158b26c991f7d6b9cd4ead625dc82ab2296c9dc277cbcdb164f8f"

static const struct c300x_patch_range MEDIA_TEARDOWN_PATCHES[] = {
    {
        "teardown_drain_0",
        0x5ee0,
        4,
        C300X_MEDIA_TEARDOWN_STOCK_RANGE_SHA256,
        C300X_MEDIA_TEARDOWN_PATCHED_RANGE_SHA256,
        MEDIA_TEARDOWN_WRITES,
        sizeof(MEDIA_TEARDOWN_WRITES) / sizeof(MEDIA_TEARDOWN_WRITES[0]),
    },
    {
        "teardown_drain_1",
        0xdd0c,
        4,
        C300X_MEDIA_TEARDOWN_STOCK_RANGE_SHA256,
        C300X_MEDIA_TEARDOWN_PATCHED_RANGE_SHA256,
        MEDIA_TEARDOWN_WRITES,
        sizeof(MEDIA_TEARDOWN_WRITES) / sizeof(MEDIA_TEARDOWN_WRITES[0]),
    },
};

#define MEDIA_TEARDOWN_PATCH_COUNT \
    (sizeof(MEDIA_TEARDOWN_PATCHES) / sizeof(MEDIA_TEARDOWN_PATCHES[0]))

static void set_err(char *error, size_t error_len, const char *message)
{
    if (error != NULL && error_len > 0) {
        c300x_copy_string(error, error_len, message != NULL ? message : "media_teardown_failed");
    }
}

static void set_status_err(struct c300x_media_teardown_status *status, const char *message)
{
    if (status != NULL) {
        c300x_copy_string(status->error, sizeof(status->error), message);
    }
}

static int target_file_name(char *buffer, size_t buffer_len)
{
    static const struct {
        size_t offset;
        char value;
    } replacements[] = {
        {0, 'b'}, {1, 't'}, {3, 'a'}, {4, 'v'},
        {6, 'm'}, {7, 'e'}, {8, 'd'}, {9, 'i'}, {10, 'a'},
    };

    if (buffer_len < sizeof(C300X_MEDIA_TEARDOWN_TARGET_MASK)) {
        return 0;
    }
    c300x_copy_string(buffer, buffer_len, C300X_MEDIA_TEARDOWN_TARGET_MASK);
    for (size_t index = 0; index < sizeof(replacements) / sizeof(replacements[0]); index++) {
        buffer[replacements[index].offset] = replacements[index].value;
    }
    return 1;
}

static int target_path(char *buffer, size_t buffer_len)
{
    const char *override = getenv("C300X_MEDIA_TEARDOWN_TARGET");
    char name[sizeof(C300X_MEDIA_TEARDOWN_TARGET_MASK)];

    if (override != NULL && override[0] != '\0') {
        c300x_copy_string(buffer, buffer_len, override);
        return 1;
    }
    if (!target_file_name(name, sizeof(name))) {
        return 0;
    }
    return snprintf(buffer, buffer_len, "%s/%s", C300X_MEDIA_TEARDOWN_TARGET_DIR, name)
        < (int)buffer_len;
}

static int backup_path(char *buffer, size_t buffer_len)
{
    const char *override = getenv("C300X_MEDIA_TEARDOWN_BACKUP_DIR");
    const char *directory = (override != NULL && override[0] != '\0')
        ? override
        : C300X_MEDIA_TEARDOWN_BACKUP_DIR;
    char name[sizeof(C300X_MEDIA_TEARDOWN_TARGET_MASK)];

    if (!target_file_name(name, sizeof(name))) {
        return 0;
    }
    return snprintf(buffer, buffer_len, "%s/%s", directory, name) < (int)buffer_len;
}

static int all_ranges_match(const unsigned char *data, size_t len, int patched)
{
    for (size_t index = 0; index < MEDIA_TEARDOWN_PATCH_COUNT; index++) {
        const struct c300x_patch_range *patch = &MEDIA_TEARDOWN_PATCHES[index];
        const char *expected = patched
            ? patch->patched_range_sha256
            : patch->expected_range_sha256;

        if (!c300x_patch_range_matches(data, len, patch, expected)) {
            return 0;
        }
    }
    return 1;
}

int c300x_media_teardown_read_status(struct c300x_media_teardown_status *status)
{
    char target[C300X_MAX_PATH_LEN];
    char backup[C300X_MAX_PATH_LEN];
    unsigned char *data = NULL;
    size_t len = 0;

    memset(status, 0, sizeof(*status));
    if (!target_path(target, sizeof(target)) || !backup_path(backup, sizeof(backup))) {
        c300x_copy_string(status->state, sizeof(status->state), "missing");
        set_status_err(status, "target_path_failed");
        return 0;
    }
    if (access(backup, F_OK) == 0) {
        status->backup_present = 1;
    }
    if (!c300x_patch_read_file(target, &data, &len)) {
        c300x_copy_string(status->state, sizeof(status->state), "missing");
        set_status_err(status, "target_missing");
        return 0;
    }
    status->supported = 1;
    if (all_ranges_match(data, len, 1)) {
        status->patched = 1;
        c300x_copy_string(status->state, sizeof(status->state), "patched");
        free(data);
        return 1;
    }
    if (all_ranges_match(data, len, 0)) {
        c300x_copy_string(status->state, sizeof(status->state), "stock");
        free(data);
        return 1;
    }
    free(data);
    c300x_copy_string(status->state, sizeof(status->state), "unsupported");
    set_status_err(status, "unsupported_target_ranges");
    return 1;
}

int c300x_media_teardown_apply(
    struct c300x_media_teardown_status *status,
    char *error,
    size_t error_len
)
{
    char target[C300X_MAX_PATH_LEN];
    char backup[C300X_MAX_PATH_LEN];
    char tmp[C300X_MAX_PATH_LEN];
    unsigned char *data = NULL;
    size_t len = 0;
    mode_t mode;
    uid_t uid;
    gid_t gid;
    FILE *fp;
    int fd;

    if (!c300x_media_teardown_read_status(status)) {
        set_err(error, error_len, status->error[0] != '\0' ? status->error : "status_failed");
        return 0;
    }
    if (status->patched) {
        return 1;
    }
    if (strcmp(status->state, "stock") != 0) {
        set_err(error, error_len, "unsupported_target_ranges");
        return 0;
    }
    if (!target_path(target, sizeof(target)) || !backup_path(backup, sizeof(backup))) {
        set_err(error, error_len, "target_path_failed");
        return 0;
    }
    if (snprintf(tmp, sizeof(tmp), "%s.tmp", target) >= (int)sizeof(tmp)) {
        set_err(error, error_len, "target_tmp_path_failed");
        return 0;
    }
    if (!c300x_patch_file_mode(target, &mode, &uid, &gid)) {
        set_err(error, error_len, "target_stat_failed");
        return 0;
    }
    if (!status->backup_present && !c300x_patch_copy_file_exact(target, backup, mode)) {
        set_err(error, error_len, "backup_failed");
        return 0;
    }
    if (!c300x_patch_read_file(target, &data, &len)) {
        set_err(error, error_len, "target_read_failed");
        return 0;
    }
    for (size_t index = 0; index < MEDIA_TEARDOWN_PATCH_COUNT; index++) {
        const struct c300x_patch_range *patch = &MEDIA_TEARDOWN_PATCHES[index];

        if (!c300x_patch_range_matches(data, len, patch, patch->expected_range_sha256)) {
            free(data);
            set_err(error, error_len, patch->name);
            return 0;
        }
        for (size_t write_index = 0; write_index < patch->write_count; write_index++) {
            const struct c300x_patch_write *write = &patch->writes[write_index];

            if (write->offset + write->len > patch->range_len) {
                free(data);
                set_err(error, error_len, patch->name);
                return 0;
            }
            memcpy(data + patch->offset + write->offset, write->data, write->len);
        }
        if (!c300x_patch_range_matches(data, len, patch, patch->patched_range_sha256)) {
            free(data);
            set_err(error, error_len, patch->name);
            return 0;
        }
    }
    if (!c300x_patch_remount_root("rw")) {
        free(data);
        set_err(error, error_len, "remount_rw_failed");
        return 0;
    }
    fp = fopen(tmp, "wb");
    if (fp == NULL || fwrite(data, 1, len, fp) != len) {
        if (fp != NULL) {
            fclose(fp);
        }
        unlink(tmp);
        (void)c300x_patch_remount_root("ro");
        free(data);
        set_err(error, error_len, "write_failed");
        return 0;
    }
    free(data);
    fd = fileno(fp);
    if (
        fd < 0
        || fchmod(fd, mode) != 0
        || (fchown(fd, uid, gid) != 0 && errno != EPERM)
    ) {
        fclose(fp);
        unlink(tmp);
        (void)c300x_patch_remount_root("ro");
        set_err(error, error_len, "target_replace_failed");
        return 0;
    }
    (void)fsync(fd);
    if (fclose(fp) != 0 || rename(tmp, target) != 0) {
        unlink(tmp);
        (void)c300x_patch_remount_root("ro");
        set_err(error, error_len, "target_replace_failed");
        return 0;
    }
    if (!c300x_patch_remount_root("ro")) {
        set_err(error, error_len, "remount_ro_failed");
        return 0;
    }
    if (!c300x_media_teardown_read_status(status) || !status->patched) {
        set_err(error, error_len, "patched_ranges_mismatch");
        return 0;
    }
    return 1;
}

int c300x_media_teardown_restore(
    struct c300x_media_teardown_status *status,
    char *error,
    size_t error_len
)
{
    char target[C300X_MAX_PATH_LEN];
    char backup[C300X_MAX_PATH_LEN];
    mode_t backup_mode;

    if (!target_path(target, sizeof(target)) || !backup_path(backup, sizeof(backup))) {
        set_err(error, error_len, "target_path_failed");
        return 0;
    }
    if (access(backup, F_OK) != 0) {
        set_err(error, error_len, "backup_missing");
        return 0;
    }
    if (!c300x_patch_file_mode(backup, &backup_mode, NULL, NULL)) {
        set_err(error, error_len, "backup_stat_failed");
        return 0;
    }
    if (!c300x_patch_remount_root("rw")) {
        set_err(error, error_len, "remount_rw_failed");
        return 0;
    }
    if (!c300x_patch_copy_file_exact(backup, target, backup_mode)) {
        (void)c300x_patch_remount_root("ro");
        set_err(error, error_len, "restore_failed");
        return 0;
    }
    if (!c300x_patch_remount_root("ro")) {
        set_err(error, error_len, "remount_ro_failed");
        return 0;
    }
    return c300x_media_teardown_read_status(status);
}
