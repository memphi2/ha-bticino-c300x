#define _POSIX_C_SOURCE 200809L

#include "display_touch.h"

#include "device_patch_io.h"
#include "sha256.h"
#include "string_util.h"

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef C300X_DISPLAY_TOUCH_TARGET_DIR
#define C300X_DISPLAY_TOUCH_TARGET_DIR "/usr/lib"
#endif
#ifndef C300X_DISPLAY_TOUCH_BACKUP_DIR
#define C300X_DISPLAY_TOUCH_BACKUP_DIR "/home/bticino/cfg/extra/c300x-device-file-backups/original/usr/lib"
#endif
#define C300X_DISPLAY_TOUCH_TARGET_MASK "l?bQ?Gu?E.so.4.8.7"

/* One build of the display library serves firmware 1.7.x and 2.0.2. Both
 * whole-file hashes are known, so a file is stock, patched or left alone. */
#ifndef C300X_DISPLAY_TOUCH_STOCK_SHA256
#define C300X_DISPLAY_TOUCH_STOCK_SHA256 "bdbff744eebe0f8acbf13d9aebb7868e2f60c9cfc9ffd1a7014abbee86701fe4"
#endif
#ifndef C300X_DISPLAY_TOUCH_PATCHED_SHA256
#define C300X_DISPLAY_TOUCH_PATCHED_SHA256 "8088d9cdc83aaecb875357becb1579be273e9c34fa28c2dadb470db6d4080b5e"
#endif
#ifndef C300X_DISPLAY_TOUCH_STOCK_RANGE_SHA256
#define C300X_DISPLAY_TOUCH_STOCK_RANGE_SHA256 "228b6d667b0c836d8ae73142d09a4adcd682a0dc12a9556833d22bb2dd007490"
#endif

#define ARRAY_LEN(values) (sizeof(values) / sizeof((values)[0]))

/* "return 16": the two instructions that replace the read of the threshold. */
static const unsigned char PATCH_0_WRITE_0[] = {0x10,0x00,0xa0,0xe3,0x1e,0xff,0x2f,0xe1};
static const struct c300x_patch_write PATCH_0_WRITES[] = {
    {0, PATCH_0_WRITE_0, sizeof(PATCH_0_WRITE_0)},
};

static const struct c300x_patch_range PATCHES[] = {
    {"touch_drag_distance", 0x180094, 8, C300X_DISPLAY_TOUCH_STOCK_RANGE_SHA256, "705b7734f4666818e8402c1879d90d2874d87ebbefa22943a419b7b4f2eb86b5", PATCH_0_WRITES, ARRAY_LEN(PATCH_0_WRITES)},
};

static int touch_path(char *buffer, size_t buffer_len, const char *directory, const char *suffix)
{
    static const struct {
        size_t offset;
        char value;
    } replacements[] = {
        {1, 'i'},
        {4, 't'},
        {7, 'i'},
    };
    char name[sizeof(C300X_DISPLAY_TOUCH_TARGET_MASK)];
    int written;

    c300x_copy_string(name, sizeof(name), C300X_DISPLAY_TOUCH_TARGET_MASK);
    for (size_t index = 0; index < ARRAY_LEN(replacements); index++) {
        name[replacements[index].offset] = replacements[index].value;
    }
    written = snprintf(buffer, buffer_len, "%s/%s%s", directory, name, suffix);
    return written >= 0 && written < (int)buffer_len;
}

static void set_error(char *error, size_t error_len, const char *message)
{
    if (error != NULL && error_len > 0) {
        c300x_copy_string(error, error_len, message);
    }
}

static int file_has_sha256(const char *path, const char *expected)
{
    char sha256[C300X_DISPLAY_TOUCH_HASH_LEN];

    return c300x_sha256_file_hex(path, sha256, sizeof(sha256)) && strcmp(sha256, expected) == 0;
}

int c300x_display_touch_read_status(struct c300x_display_touch_status *status)
{
    char target_path[C300X_MAX_PATH_LEN];
    char backup_path[C300X_MAX_PATH_LEN];

    memset(status, 0, sizeof(*status));
    c300x_copy_string(status->state, sizeof(status->state), "missing");
    if (
        !touch_path(target_path, sizeof(target_path), C300X_DISPLAY_TOUCH_TARGET_DIR, "")
        || !touch_path(backup_path, sizeof(backup_path), C300X_DISPLAY_TOUCH_BACKUP_DIR, "")
    ) {
        c300x_copy_string(status->error, sizeof(status->error), "touch_path_failed");
        return 0;
    }
    status->backup_present = access(backup_path, F_OK) == 0;
    if (!c300x_sha256_file_hex(target_path, status->file_sha256, sizeof(status->file_sha256))) {
        return 1;
    }
    if (strcmp(status->file_sha256, C300X_DISPLAY_TOUCH_STOCK_SHA256) == 0) {
        c300x_copy_string(status->state, sizeof(status->state), "stock");
    } else if (strcmp(status->file_sha256, C300X_DISPLAY_TOUCH_PATCHED_SHA256) == 0) {
        status->patched = 1;
        c300x_copy_string(status->state, sizeof(status->state), "patched");
    } else {
        c300x_copy_string(status->state, sizeof(status->state), "unsupported");
    }
    return 1;
}

/* The stock file with the writes applied, checked range by range and as a whole. */
static int patched_content(const char *target_path, unsigned char **data, size_t *len)
{
    char sha256[C300X_DISPLAY_TOUCH_HASH_LEN];

    if (!c300x_patch_read_file(target_path, data, len)) {
        return 0;
    }
    for (size_t index = 0; index < ARRAY_LEN(PATCHES); index++) {
        const struct c300x_patch_range *patch = &PATCHES[index];

        if (!c300x_patch_range_matches(*data, *len, patch, patch->expected_range_sha256)) {
            goto failed;
        }
        for (size_t write_index = 0; write_index < patch->write_count; write_index++) {
            const struct c300x_patch_write *write = &patch->writes[write_index];

            if (write->offset + write->len > patch->range_len) {
                goto failed;
            }
            memcpy(*data + patch->offset + write->offset, write->data, write->len);
        }
        if (!c300x_patch_range_matches(*data, *len, patch, patch->patched_range_sha256)) {
            goto failed;
        }
    }
    if (
        c300x_sha256_bytes_hex(*data, *len, sha256, sizeof(sha256))
        && strcmp(sha256, C300X_DISPLAY_TOUCH_PATCHED_SHA256) == 0
    ) {
        return 1;
    }
failed:
    free(*data);
    *data = NULL;
    return 0;
}

static int write_and_replace(
    const char *target_path,
    const unsigned char *data,
    size_t len,
    mode_t mode,
    uid_t uid,
    gid_t gid,
    const char *expected_sha256
)
{
    char tmp_path[C300X_MAX_PATH_LEN];
    FILE *fp;
    int fd;

    if (snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", target_path) >= (int)sizeof(tmp_path)) {
        return 0;
    }
    fp = fopen(tmp_path, "wb");
    if (fp == NULL) {
        return 0;
    }
    fd = fileno(fp);
    if (
        fwrite(data, 1, len, fp) != len
        || fflush(fp) != 0
        || fd < 0
        || fchmod(fd, mode) != 0
        || (fchown(fd, uid, gid) != 0 && errno != EPERM)
        || fsync(fd) != 0
    ) {
        fclose(fp);
        unlink(tmp_path);
        return 0;
    }
    if (fclose(fp) != 0 || !file_has_sha256(tmp_path, expected_sha256)) {
        unlink(tmp_path);
        return 0;
    }
    /* A rename leaves the running display on the file it has open. */
    if (rename(tmp_path, target_path) != 0) {
        unlink(tmp_path);
        return 0;
    }
    return 1;
}

/* A run that was cut off while writing leaves its temporary file behind. */
static void drop_stale_temp(void)
{
    char tmp_path[C300X_MAX_PATH_LEN];

    if (
        touch_path(tmp_path, sizeof(tmp_path), C300X_DISPLAY_TOUCH_TARGET_DIR, ".tmp")
        && access(tmp_path, F_OK) == 0
        && c300x_patch_remount_root("rw")
    ) {
        (void)unlink(tmp_path);
        (void)c300x_patch_remount_root("ro");
    }
}

/* A job stopped between the rw and the ro remount would leave / writable
 * with nobody told. Stop signals wait until / is read-only again; one that
 * came in then fails the run, and stays blocked until the result is out. */
static void hold_stop_signals(sigset_t *previous)
{
    sigset_t stop;
    sigemptyset(&stop);
    sigaddset(&stop, SIGTERM);
    sigaddset(&stop, SIGINT);
    sigaddset(&stop, SIGHUP);
    sigprocmask(SIG_BLOCK, &stop, previous);
}

static int release_stop_signals(const sigset_t *previous)
{
    sigset_t pending;
    if (sigpending(&pending) == 0 && (sigismember(&pending, SIGTERM) == 1
        || sigismember(&pending, SIGINT) == 1 || sigismember(&pending, SIGHUP) == 1)) {
        return 1;
    }
    sigprocmask(SIG_SETMASK, previous, NULL);
    return 0;
}

int c300x_display_touch_apply(
    struct c300x_display_touch_status *status,
    char *error,
    size_t error_len
)
{
    char target_path[C300X_MAX_PATH_LEN];
    char backup_path[C300X_MAX_PATH_LEN];
    unsigned char *data = NULL;
    size_t len = 0;
    mode_t mode;
    uid_t uid;
    gid_t gid;
    int written;
    int root_writable;
    sigset_t previous;

    drop_stale_temp();
    if (!c300x_display_touch_read_status(status)) {
        set_error(error, error_len, "touch_status_failed");
        return 0;
    }
    if (status->patched) {
        return 1;
    }
    if (strcmp(status->state, "stock") != 0) {
        set_error(error, error_len, "unsupported_touch_target_hash");
        return 0;
    }
    if (
        !touch_path(target_path, sizeof(target_path), C300X_DISPLAY_TOUCH_TARGET_DIR, "")
        || !touch_path(backup_path, sizeof(backup_path), C300X_DISPLAY_TOUCH_BACKUP_DIR, "")
        || !c300x_patch_file_mode(target_path, &mode, &uid, &gid)
    ) {
        set_error(error, error_len, "touch_target_stat_failed");
        return 0;
    }
    if (
        !file_has_sha256(backup_path, C300X_DISPLAY_TOUCH_STOCK_SHA256)
        && (
            !c300x_patch_copy_file_exact(target_path, backup_path, mode)
            || !file_has_sha256(backup_path, C300X_DISPLAY_TOUCH_STOCK_SHA256)
        )
    ) {
        set_error(error, error_len, "touch_backup_failed");
        return 0;
    }
    if (!patched_content(target_path, &data, &len)) {
        set_error(error, error_len, "touch_ranges_mismatch");
        return 0;
    }
    hold_stop_signals(&previous);
    if (!c300x_patch_remount_root("rw")) {
        free(data);
        (void)release_stop_signals(&previous);
        set_error(error, error_len, "remount_rw_failed");
        return 0;
    }
    written = write_and_replace(
        target_path, data, len, mode, uid, gid, C300X_DISPLAY_TOUCH_PATCHED_SHA256
    );
    free(data);
    root_writable = !c300x_patch_remount_root("ro");
    (void)c300x_display_touch_read_status(status);
    status->changed = written;
    status->root_writable = root_writable;
    if (release_stop_signals(&previous)) {
        set_error(error, error_len, "touch_interrupted");
        return 0;
    }
    if (!written) {
        set_error(error, error_len, "touch_write_failed");
        return 0;
    }
    if (!status->patched) {
        set_error(error, error_len, "touch_patched_hash_mismatch");
        return 0;
    }
    return 1;
}

int c300x_display_touch_restore(
    struct c300x_display_touch_status *status,
    char *error,
    size_t error_len
)
{
    char target_path[C300X_MAX_PATH_LEN];
    char backup_path[C300X_MAX_PATH_LEN];
    char sha256[C300X_DISPLAY_TOUCH_HASH_LEN];
    unsigned char *data = NULL;
    size_t len = 0;
    mode_t mode;
    uid_t uid;
    gid_t gid;
    int written;
    int root_writable;
    sigset_t previous;

    drop_stale_temp();
    if (!c300x_display_touch_read_status(status)) {
        set_error(error, error_len, "touch_status_failed");
        return 0;
    }
    /* Only the file this patch wrote is replaced, and only by the stock file. */
    if (!status->patched) {
        return 1;
    }
    if (
        !touch_path(target_path, sizeof(target_path), C300X_DISPLAY_TOUCH_TARGET_DIR, "")
        || !touch_path(backup_path, sizeof(backup_path), C300X_DISPLAY_TOUCH_BACKUP_DIR, "")
        || !c300x_patch_file_mode(target_path, &mode, &uid, &gid)
    ) {
        set_error(error, error_len, "touch_target_stat_failed");
        return 0;
    }
    if (
        !c300x_patch_read_file(backup_path, &data, &len)
        || !c300x_sha256_bytes_hex(data, len, sha256, sizeof(sha256))
        || strcmp(sha256, C300X_DISPLAY_TOUCH_STOCK_SHA256) != 0
    ) {
        free(data);
        set_error(error, error_len, "touch_backup_invalid");
        return 0;
    }
    hold_stop_signals(&previous);
    if (!c300x_patch_remount_root("rw")) {
        free(data);
        (void)release_stop_signals(&previous);
        set_error(error, error_len, "remount_rw_failed");
        return 0;
    }
    written = write_and_replace(
        target_path, data, len, mode, uid, gid, C300X_DISPLAY_TOUCH_STOCK_SHA256
    );
    free(data);
    root_writable = !c300x_patch_remount_root("ro");
    (void)c300x_display_touch_read_status(status);
    status->changed = written;
    status->root_writable = root_writable;
    if (release_stop_signals(&previous)) {
        set_error(error, error_len, "touch_interrupted");
        return 0;
    }
    if (!written) {
        set_error(error, error_len, "touch_restore_failed");
        return 0;
    }
    if (strcmp(status->state, "stock") != 0) {
        set_error(error, error_len, "touch_restore_hash_mismatch");
        return 0;
    }
    return 1;
}

int c300x_display_touch_cli(const char *action)
{
    struct c300x_display_touch_status status;
    char error[C300X_MAX_ERROR_LEN] = {0};
    int ok;

    if (strcmp(action, "status") == 0) {
        ok = c300x_display_touch_read_status(&status);
    } else if (strcmp(action, "apply") == 0) {
        ok = c300x_display_touch_apply(&status, error, sizeof(error));
    } else if (strcmp(action, "restore") == 0) {
        ok = c300x_display_touch_restore(&status, error, sizeof(error));
    } else {
        fprintf(stderr, "fatal: invalid_arguments: --display-touch needs status|apply|restore\n");
        return 2;
    }
    printf(
        "{\"ok\":%s,\"state\":\"%s\",\"patched\":%s,\"backup_present\":%s,\"changed\":%s,"
        "\"root_writable\":%s,\"error\":\"%s\"}\n",
        ok ? "true" : "false",
        status.state,
        status.patched ? "true" : "false",
        status.backup_present ? "true" : "false",
        status.changed ? "true" : "false",
        status.root_writable ? "true" : "false",
        error
    );
    return ok ? 0 : 1;
}
