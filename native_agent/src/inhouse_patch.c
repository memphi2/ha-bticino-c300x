#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#define _POSIX_C_SOURCE 200809L

#include "inhouse_patch.h"

#include "sha256.h"
#include "string_util.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <sys/stat.h>
#include <unistd.h>

#define BT_ANSWERING_MACHINE_PATH "/home/bticino/bin/bt_answering_machine"
#define BT_ANSWERING_MACHINE_BACKUP "/home/bticino/cfg/extra/c300x-device-file-backups/original/home/bticino/bin/bt_answering_machine"
#define BT_ANSWERING_MACHINE_STOCK_SHA256 "605a808f1ed0c826c06bbf1eb4131b9198007a7ab822e7541a6666e79816c810"
#define BT_ANSWERING_MACHINE_PATCHED_SHA256 "8f6e45d4c5f94bab74fa1dc8bd9ce06ca76a3a499dc664a9c6dbd934943e1c13"

struct binary_patch {
    const char *name;
    size_t offset;
    const unsigned char *original;
    const unsigned char *patched;
    size_t len;
};

#ifdef __arm__
#define C300X_INHOUSE_STAT_STRUCT struct stat64
#else
#define C300X_INHOUSE_STAT_STRUCT struct stat
#endif

static int inhouse_stat_path(const char *path, C300X_INHOUSE_STAT_STRUCT *status)
{
#ifdef __arm__
    return (int)syscall(SYS_stat64, path, status);
#else
    return stat(path, status);
#endif
}

static const unsigned char PATCH_0_ORIG[] = {0x02,0x30,0xd0,0xe3,0x00,0x80,0xa0,0xe1,0x2f,0x00,0x00,0x1a};
static const unsigned char PATCH_0_NEW[] = {0x02,0x00,0x50,0xe3,0x00,0x80,0xa0,0xe1,0x2f,0x00,0x00,0x8a};
static const unsigned char PATCH_1_ORIG[] = {0x02,0x50,0xd0,0xe3,0x01,0x50,0xa0,0x13,0x01,0x00,0x00,0x0a,0x05,0x00,0xa0,0xe1};
static const unsigned char PATCH_1_NEW[] = {0x02,0x00,0x50,0xe3,0x00,0x50,0xa0,0x93,0x01,0x00,0x00,0x9a,0x01,0x00,0xa0,0xe3};
static const unsigned char PATCH_2_ORIG[] = {0x3a,0xff,0x2f,0xe1};
static const unsigned char PATCH_2_NEW[] = {0x00,0x00,0xa0,0xe1};
static const unsigned char PATCH_3_ORIG[] = {0xb4,0xb3,0x84,0xe5};
static const unsigned char PATCH_3_NEW[] = {0x00,0x00,0xa0,0xe1};
static const unsigned char PATCH_4_ORIG[] = {0x06,0x20,0xa0,0xe1,0x04,0x10,0xa0,0xe1,0x0b,0x00,0xa0,0xe1,0x7b,0x5e,0xff,0xeb};
static const unsigned char PATCH_4_NEW[] = {0x00,0x00,0xa0,0xe1,0x00,0x00,0xa0,0xe1,0x00,0x00,0xa0,0xe1,0x00,0x00,0xa0,0xe1};
static const unsigned char PATCH_5_ORIG[] = {0x6c,0x62,0x00,0x00};
static const unsigned char PATCH_5_NEW[] = {0x8c,0x78,0x00,0x00};
static const unsigned char PATCH_6_ORIG[] = {
    0x7c,0x21,0x9f,0xe5,0x7c,0x31,0x9f,0xe5,0x02,0x90,0x96,0xe7,
    0x03,0x60,0x96,0xe7,0x04,0x30,0x99,0xe5,0x00,0x20,0x96,0xe5,
    0x01,0x00,0x13,0xe3,0xc3,0x00,0x82,0xe0,0x00,0xa0,0x99,0xe5,
    0xc3,0x30,0x92,0x17,0x5c,0x21,0x9f,0xe5,0x0a,0xa0,0x93,0x17,
    0x02,0x20,0x8f,0xe0,0x02,0x10,0xa0,0xe3,0x3a,0xff,0x2f,0xe1
};
static const unsigned char PATCH_6_NEW[] = {
    0x01,0x00,0x58,0xe3,0x05,0x00,0x00,0x1a,0x70,0x21,0x9f,0xe5,
    0x78,0x11,0x9f,0xe5,0x02,0x20,0x8f,0xe0,0x01,0x10,0x8f,0xe0,
    0x05,0x00,0xa0,0xe1,0x6c,0xc3,0xff,0xeb,0x5c,0x21,0x9f,0xe5,
    0x5c,0x31,0x9f,0xe5,0x02,0x90,0x96,0xe7,0x03,0x60,0x96,0xe7,
    0x00,0x00,0xa0,0xe1,0x00,0x00,0xa0,0xe1,0x00,0x00,0xa0,0xe1
};
static const unsigned char PATCH_7_ORIG[] = {0x30,0x1e,0x01,0x00};
static const unsigned char PATCH_7_NEW[] = {0x48,0x54,0x01,0x00};
static const unsigned char PATCH_8_ORIG[] = {0x64,0x3e,0x01,0x00};
static const unsigned char PATCH_8_NEW[] = {0x48,0x3e,0x01,0x00};

static const struct binary_patch PATCHES[] = {
    {"allow_dimension_37_values", 0x282f8, PATCH_0_ORIG, PATCH_0_NEW, sizeof(PATCH_0_ORIG)},
    {"allow_disable_remote_values", 0xda04, PATCH_1_ORIG, PATCH_1_NEW, sizeof(PATCH_1_ORIG)},
    {"suppress_inhouse_disabled_log", 0x35fe0, PATCH_2_ORIG, PATCH_2_NEW, sizeof(PATCH_2_ORIG)},
    {"keep_disable_remote", 0x35ff4, PATCH_3_ORIG, PATCH_3_NEW, sizeof(PATCH_3_ORIG)},
    {"preserve_route_mode", 0x36000, PATCH_4_ORIG, PATCH_4_NEW, sizeof(PATCH_4_ORIG)},
    {"route_disable_remote_to_int", 0x363d8, PATCH_5_ORIG, PATCH_5_NEW, sizeof(PATCH_5_ORIG)},
    {"runtime_inhouse_route_int", 0x28420, PATCH_6_ORIG, PATCH_6_NEW, sizeof(PATCH_6_ORIG)},
    {"runtime_route_target", 0x285a0, PATCH_7_ORIG, PATCH_7_NEW, sizeof(PATCH_7_ORIG)},
    {"runtime_route_link", 0x285ac, PATCH_8_ORIG, PATCH_8_NEW, sizeof(PATCH_8_ORIG)},
};

static void set_error(char *error, size_t error_len, const char *message)
{
    if (error != NULL && error_len > 0) {
        c300x_copy_string(error, error_len, message != NULL ? message : "inhouse_patch_failed");
    }
}

static void set_status_error(struct c300x_inhouse_binary_patch_status *status, const char *message)
{
    if (status != NULL) {
        c300x_copy_string(status->error, sizeof(status->error), message);
    }
}

static int ensure_parent_dir(const char *path)
{
    char buffer[C300X_MAX_PATH_LEN];
    char *slash;

    if (strlen(path) >= sizeof(buffer)) {
        return 0;
    }
    c300x_copy_string(buffer, sizeof(buffer), path);
    slash = strrchr(buffer, '/');
    if (slash == NULL) {
        return 1;
    }
    *slash = '\0';
    for (char *p = buffer + 1; *p != '\0'; p++) {
        if (*p == '/') {
            *p = '\0';
            if (mkdir(buffer, 0755) != 0 && errno != EEXIST) {
                return 0;
            }
            *p = '/';
        }
    }
    return mkdir(buffer, 0755) == 0 || errno == EEXIST;
}

static int copy_file_exact(const char *source, const char *target, mode_t mode)
{
    char tmp_path[C300X_MAX_PATH_LEN];
    C300X_INHOUSE_STAT_STRUCT source_stat;
    FILE *in;
    FILE *out;
    int fd;
    unsigned char buffer[4096];
    size_t read_len;

    if (!ensure_parent_dir(target)) {
        return 0;
    }
    if (snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", target) >= (int)sizeof(tmp_path)) {
        return 0;
    }
    if (inhouse_stat_path(source, &source_stat) != 0) {
        return 0;
    }
    in = fopen(source, "rb");
    if (in == NULL) {
        return 0;
    }
    out = fopen(tmp_path, "wb");
    if (out == NULL) {
        fclose(in);
        return 0;
    }
    while ((read_len = fread(buffer, 1, sizeof(buffer), in)) > 0) {
        if (fwrite(buffer, 1, read_len, out) != read_len) {
            fclose(in);
            fclose(out);
            unlink(tmp_path);
            return 0;
        }
    }
    if (ferror(in)) {
        fclose(in);
        fclose(out);
        unlink(tmp_path);
        return 0;
    }
    fclose(in);
    fd = fileno(out);
    if (fd >= 0) {
        (void)fsync(fd);
    }
    if (fclose(out) != 0) {
        unlink(tmp_path);
        return 0;
    }
    if (chmod(tmp_path, mode) != 0) {
        unlink(tmp_path);
        return 0;
    }
    if (chown(tmp_path, source_stat.st_uid, source_stat.st_gid) != 0 && errno != EPERM) {
        unlink(tmp_path);
        return 0;
    }
    if (rename(tmp_path, target) != 0) {
        unlink(tmp_path);
        return 0;
    }
    return 1;
}

static int remount_root(const char *mode)
{
    char command[64];
    int status;

    if (snprintf(command, sizeof(command), "mount -o remount,%s / >/dev/null 2>&1", mode) >= (int)sizeof(command)) {
        return 0;
    }
    status = system(command);
    return status == 0;
}

static int remount_root_ro_or_error(char *error, size_t error_len)
{
    if (remount_root("ro")) {
        return 1;
    }
    set_error(error, error_len, "remount_ro_failed");
    return 0;
}

static int read_file(const char *path, unsigned char **data, size_t *len)
{
    C300X_INHOUSE_STAT_STRUCT st;
    FILE *fp;
    size_t read_len;

    *data = NULL;
    *len = 0;
    if (inhouse_stat_path(path, &st) != 0 || st.st_size <= 0) {
        return 0;
    }
    *data = malloc((size_t)st.st_size);
    if (*data == NULL) {
        return 0;
    }
    fp = fopen(path, "rb");
    if (fp == NULL) {
        free(*data);
        *data = NULL;
        return 0;
    }
    read_len = fread(*data, 1, (size_t)st.st_size, fp);
    if (ferror(fp) || read_len != (size_t)st.st_size) {
        fclose(fp);
        free(*data);
        *data = NULL;
        return 0;
    }
    fclose(fp);
    *len = read_len;
    return 1;
}

int c300x_inhouse_binary_patch_read_status(
    struct c300x_inhouse_binary_patch_status *status
)
{
    memset(status, 0, sizeof(*status));
    status->supported = 1;
    if (!c300x_sha256_file_hex(BT_ANSWERING_MACHINE_PATH, status->file_sha256, sizeof(status->file_sha256))) {
        c300x_copy_string(status->state, sizeof(status->state), "missing");
        set_status_error(status, "binary_missing");
        return 0;
    }
    if (access(BT_ANSWERING_MACHINE_BACKUP, F_OK) == 0) {
        status->backup_present = 1;
        (void)c300x_sha256_file_hex(BT_ANSWERING_MACHINE_BACKUP, status->backup_sha256, sizeof(status->backup_sha256));
    }
    if (strcmp(status->file_sha256, BT_ANSWERING_MACHINE_PATCHED_SHA256) == 0) {
        status->patched = 1;
        c300x_copy_string(status->state, sizeof(status->state), "patched");
        return 1;
    }
    if (strcmp(status->file_sha256, BT_ANSWERING_MACHINE_STOCK_SHA256) == 0) {
        c300x_copy_string(status->state, sizeof(status->state), "stock");
        return 1;
    }
    c300x_copy_string(status->state, sizeof(status->state), "unsupported");
    set_status_error(status, "unsupported_binary_hash");
    return 1;
}

int c300x_inhouse_binary_patch_apply(
    struct c300x_inhouse_binary_patch_status *status,
    char *error,
    size_t error_len
)
{
    unsigned char *data = NULL;
    size_t len = 0;
    C300X_INHOUSE_STAT_STRUCT original_stat;
    mode_t original_mode;
    char digest[C300X_INHOUSE_PATCH_HASH_LEN];
    FILE *fp;

    if (!c300x_inhouse_binary_patch_read_status(status)) {
        set_error(error, error_len, "binary_status_failed");
        return 0;
    }
    if (status->patched) {
        return 1;
    }
    if (strcmp(status->state, "stock") != 0) {
        set_error(error, error_len, "unsupported_binary_hash");
        return 0;
    }
    if (inhouse_stat_path(BT_ANSWERING_MACHINE_PATH, &original_stat) != 0) {
        set_error(error, error_len, "binary_stat_failed");
        return 0;
    }
    original_mode = (mode_t)(original_stat.st_mode & 07777);
    if (!status->backup_present && !copy_file_exact(BT_ANSWERING_MACHINE_PATH, BT_ANSWERING_MACHINE_BACKUP, original_mode)) {
        set_error(error, error_len, "binary_backup_failed");
        return 0;
    }
    if (!read_file(BT_ANSWERING_MACHINE_PATH, &data, &len)) {
        set_error(error, error_len, "binary_read_failed");
        return 0;
    }
    for (size_t index = 0; index < sizeof(PATCHES) / sizeof(PATCHES[0]); index++) {
        const struct binary_patch *patch = &PATCHES[index];
        if (patch->offset + patch->len > len || memcmp(data + patch->offset, patch->original, patch->len) != 0) {
            free(data);
            set_error(error, error_len, patch->name);
            return 0;
        }
        memcpy(data + patch->offset, patch->patched, patch->len);
    }
    if (!remount_root("rw")) {
        free(data);
        set_error(error, error_len, "remount_rw_failed");
        return 0;
    }
    fp = fopen(BT_ANSWERING_MACHINE_PATH ".tmp", "wb");
    if (fp == NULL || fwrite(data, 1, len, fp) != len) {
        if (fp != NULL) {
            fclose(fp);
        }
        unlink(BT_ANSWERING_MACHINE_PATH ".tmp");
        (void)remount_root("ro");
        free(data);
        set_error(error, error_len, "binary_write_failed");
        return 0;
    }
    free(data);
    (void)fsync(fileno(fp));
    if (
        fclose(fp) != 0
        || chmod(BT_ANSWERING_MACHINE_PATH ".tmp", original_mode) != 0
        || (chown(BT_ANSWERING_MACHINE_PATH ".tmp", original_stat.st_uid, original_stat.st_gid) != 0 && errno != EPERM)
        || rename(BT_ANSWERING_MACHINE_PATH ".tmp", BT_ANSWERING_MACHINE_PATH) != 0
    ) {
        unlink(BT_ANSWERING_MACHINE_PATH ".tmp");
        (void)remount_root("ro");
        set_error(error, error_len, "binary_replace_failed");
        return 0;
    }
    if (!remount_root_ro_or_error(error, error_len)) {
        return 0;
    }
    if (!c300x_sha256_file_hex(BT_ANSWERING_MACHINE_PATH, digest, sizeof(digest)) || strcmp(digest, BT_ANSWERING_MACHINE_PATCHED_SHA256) != 0) {
        set_error(error, error_len, "patched_hash_mismatch");
        return 0;
    }
    return c300x_inhouse_binary_patch_read_status(status);
}

int c300x_inhouse_binary_patch_restore(
    struct c300x_inhouse_binary_patch_status *status,
    char *error,
    size_t error_len
)
{
    C300X_INHOUSE_STAT_STRUCT backup_stat;
    mode_t backup_mode;

    if (access(BT_ANSWERING_MACHINE_BACKUP, F_OK) != 0) {
        set_error(error, error_len, "binary_backup_missing");
        return 0;
    }
    if (inhouse_stat_path(BT_ANSWERING_MACHINE_BACKUP, &backup_stat) != 0) {
        set_error(error, error_len, "binary_backup_stat_failed");
        return 0;
    }
    backup_mode = (mode_t)(backup_stat.st_mode & 07777);
    if (!remount_root("rw")) {
        set_error(error, error_len, "remount_rw_failed");
        return 0;
    }
    if (!copy_file_exact(BT_ANSWERING_MACHINE_BACKUP, BT_ANSWERING_MACHINE_PATH, backup_mode)) {
        (void)remount_root("ro");
        set_error(error, error_len, "binary_restore_failed");
        return 0;
    }
    if (!remount_root_ro_or_error(error, error_len)) {
        return 0;
    }
    return c300x_inhouse_binary_patch_read_status(status);
}
