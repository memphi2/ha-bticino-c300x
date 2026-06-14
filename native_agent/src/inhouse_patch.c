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

#define C300X_DEVICE_PATCH_TARGET_DIR "/home/bticino/bin"
#define C300X_DEVICE_PATCH_BACKUP_DIR "/home/bticino/cfg/extra/c300x-device-file-backups/original/home/bticino/bin"
#define C300X_DEVICE_PATCH_TARGET_MASK "b?_a?sw?rin?_?ac?ine"
#define C300X_DEVICE_PATCH_STOCK_SHA256 "605a808f1ed0c826c06bbf1eb4131b9198007a7ab822e7541a6666e79816c810"

#define ARRAY_LEN(values) (sizeof(values) / sizeof((values)[0]))

struct binary_write {
    size_t offset;
    const unsigned char *data;
    size_t len;
};

struct binary_patch {
    const char *name;
    size_t offset;
    size_t range_len;
    const char *expected_range_sha256;
    const char *patched_range_sha256;
    const struct binary_write *writes;
    size_t write_count;
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

static int device_patch_file_name(char *buffer, size_t buffer_len)
{
    static const struct {
        size_t offset;
        char value;
    } replacements[] = {
        {1, 't'},
        {4, 'n'},
        {7, 'e'},
        {11, 'g'},
        {13, 'm'},
        {16, 'h'},
    };

    if (buffer_len < sizeof(C300X_DEVICE_PATCH_TARGET_MASK)) {
        return 0;
    }
    c300x_copy_string(buffer, buffer_len, C300X_DEVICE_PATCH_TARGET_MASK);
    for (size_t index = 0; index < ARRAY_LEN(replacements); index++) {
        buffer[replacements[index].offset] = replacements[index].value;
    }
    return 1;
}

static int device_patch_path(char *buffer, size_t buffer_len, const char *directory)
{
    char name[sizeof(C300X_DEVICE_PATCH_TARGET_MASK)];
    int written;

    if (!device_patch_file_name(name, sizeof(name))) {
        return 0;
    }
    written = snprintf(buffer, buffer_len, "%s/%s", directory, name);
    return written >= 0 && written < (int)buffer_len;
}

static int device_patch_target_path(char *buffer, size_t buffer_len)
{
    return device_patch_path(buffer, buffer_len, C300X_DEVICE_PATCH_TARGET_DIR);
}

static int device_patch_backup_path(char *buffer, size_t buffer_len)
{
    return device_patch_path(buffer, buffer_len, C300X_DEVICE_PATCH_BACKUP_DIR);
}

static int device_patch_temp_path(char *buffer, size_t buffer_len, const char *path)
{
    int written = snprintf(buffer, buffer_len, "%s.tmp", path);

    return written >= 0 && written < (int)buffer_len;
}

static const unsigned char PATCH_0_WRITE_0[] = {0x00,0x50};
static const unsigned char PATCH_0_WRITE_1[] = {0x8a};
static const struct binary_write PATCH_0_WRITES[] = {
    {1, PATCH_0_WRITE_0, sizeof(PATCH_0_WRITE_0)},
    {11, PATCH_0_WRITE_1, sizeof(PATCH_0_WRITE_1)},
};
static const unsigned char PATCH_1_WRITE_0[] = {0x00,0x50};
static const unsigned char PATCH_1_WRITE_1[] = {0x00};
static const unsigned char PATCH_1_WRITE_2[] = {0x93};
static const unsigned char PATCH_1_WRITE_3[] = {0x9a,0x01};
static const unsigned char PATCH_1_WRITE_4[] = {0xe3};
static const struct binary_write PATCH_1_WRITES[] = {
    {1, PATCH_1_WRITE_0, sizeof(PATCH_1_WRITE_0)},
    {4, PATCH_1_WRITE_1, sizeof(PATCH_1_WRITE_1)},
    {7, PATCH_1_WRITE_2, sizeof(PATCH_1_WRITE_2)},
    {11, PATCH_1_WRITE_3, sizeof(PATCH_1_WRITE_3)},
    {15, PATCH_1_WRITE_4, sizeof(PATCH_1_WRITE_4)},
};
static const unsigned char PATCH_2_WRITE_0[] = {0x00,0x00,0xa0};
static const struct binary_write PATCH_2_WRITES[] = {
    {0, PATCH_2_WRITE_0, sizeof(PATCH_2_WRITE_0)},
};
static const unsigned char PATCH_3_WRITE_0[] = {0x00,0x00,0xa0,0xe1};
static const struct binary_write PATCH_3_WRITES[] = {
    {0, PATCH_3_WRITE_0, sizeof(PATCH_3_WRITE_0)},
};
static const unsigned char PATCH_4_WRITE_0[] = {0x00,0x00};
static const unsigned char PATCH_4_WRITE_1[] = {0x00,0x00};
static const unsigned char PATCH_4_WRITE_2[] = {0x00};
static const unsigned char PATCH_4_WRITE_3[] = {0x00,0x00,0xa0,0xe1};
static const struct binary_write PATCH_4_WRITES[] = {
    {0, PATCH_4_WRITE_0, sizeof(PATCH_4_WRITE_0)},
    {4, PATCH_4_WRITE_1, sizeof(PATCH_4_WRITE_1)},
    {8, PATCH_4_WRITE_2, sizeof(PATCH_4_WRITE_2)},
    {12, PATCH_4_WRITE_3, sizeof(PATCH_4_WRITE_3)},
};
static const unsigned char PATCH_5_WRITE_0[] = {0x8c,0x78};
static const struct binary_write PATCH_5_WRITES[] = {
    {0, PATCH_5_WRITE_0, sizeof(PATCH_5_WRITE_0)},
};
static const unsigned char PATCH_6_WRITE_0[] = {
    0x01,0x00,0x58,0xe3,0x05,0x00,0x00,0x1a,0x70,0x21,0x9f,0xe5,
    0x78,0x11,0x9f,0xe5,0x02,0x20,0x8f,0xe0,0x01,0x10,0x8f,0xe0,
    0x05
};
static const unsigned char PATCH_6_WRITE_1[] = {
    0xa0,0xe1,0x6c,0xc3,0xff,0xeb,0x5c,0x21,0x9f
};
static const unsigned char PATCH_6_WRITE_2[] = {
    0x5c,0x31,0x9f,0xe5,0x02,0x90,0x96,0xe7,0x03,0x60,0x96,0xe7,
    0x00,0x00,0xa0,0xe1,0x00,0x00
};
static const unsigned char PATCH_6_WRITE_3[] = {0xe1,0x00,0x00,0xa0};
static const struct binary_write PATCH_6_WRITES[] = {
    {0, PATCH_6_WRITE_0, sizeof(PATCH_6_WRITE_0)},
    {26, PATCH_6_WRITE_1, sizeof(PATCH_6_WRITE_1)},
    {36, PATCH_6_WRITE_2, sizeof(PATCH_6_WRITE_2)},
    {55, PATCH_6_WRITE_3, sizeof(PATCH_6_WRITE_3)},
};
static const unsigned char PATCH_7_WRITE_0[] = {0x48,0x54};
static const struct binary_write PATCH_7_WRITES[] = {
    {0, PATCH_7_WRITE_0, sizeof(PATCH_7_WRITE_0)},
};
static const unsigned char PATCH_8_WRITE_0[] = {0x48};
static const struct binary_write PATCH_8_WRITES[] = {
    {0, PATCH_8_WRITE_0, sizeof(PATCH_8_WRITE_0)},
};

static const struct binary_patch PATCHES[] = {
    {"patch_range_0", 0x282f8, 12, "ed451a5b137b7b59ebfd3f4bb8ff6598a18abce58603b72eed97f50b8d6391b8", "59e44ff04f935f33e91e44d52771e6188e7a50c735c07b54f236087a818925d7", PATCH_0_WRITES, ARRAY_LEN(PATCH_0_WRITES)},
    {"patch_range_1", 0xda04, 16, "cad698e029e49e8557fa4259c816e318021875a348f0d2b967ed1579fce8439b", "9bf52da965bdf744685e93b31353826af7bc74bc1fc3248d91f3b89f493444fe", PATCH_1_WRITES, ARRAY_LEN(PATCH_1_WRITES)},
    {"patch_range_2", 0x35fe0, 4, "85a84a4f037c33de92504a8958803d3ca0aa78d17145ea83a7683d3f2fcc2547", "71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d", PATCH_2_WRITES, ARRAY_LEN(PATCH_2_WRITES)},
    {"patch_range_3", 0x35ff4, 4, "4954ed54e1284656fc34df4acf32b7bb7239c20a64300e0d7698c727e1de8391", "71b1548a3867fe8e62a860f8010becb36b0386c9e97d552809cebccb9d93881d", PATCH_3_WRITES, ARRAY_LEN(PATCH_3_WRITES)},
    {"patch_range_4", 0x36000, 16, "52c4701f0ebe03e78c0fed564727560fa0fc58e477656da7c254df341da5a55f", "801b48661d2b117e9d4c1065f5b27b8e68938ac8efaf47e5a1db1211d495f592", PATCH_4_WRITES, ARRAY_LEN(PATCH_4_WRITES)},
    {"patch_range_5", 0x363d8, 4, "578b7e8e1392acf5b7a042f27140fdff16d967de87b359c4629374f363061deb", "588247adc40731e7dac725b7c418ce8dedc2a7318e61f12836086f31d5d41520", PATCH_5_WRITES, ARRAY_LEN(PATCH_5_WRITES)},
    {"patch_range_6", 0x28420, 60, "4a113f9e80b59325c236497a1f60eb4c25ecfc818d846bc838d30d7a9d153d48", "16f1f5712d28c39b0e2ddf193b57ea53b9d8f498d42cee86625f2ff2792eef5c", PATCH_6_WRITES, ARRAY_LEN(PATCH_6_WRITES)},
    {"patch_range_7", 0x285a0, 4, "c77ead30bd3f6cae55371b8695c71e4c28de7b2006d3f17cd0a2629cdc98a5df", "27d18ebd92839189526cb6345d7f2d5e043d7551446dd60407975ef0e46e5cc4", PATCH_7_WRITES, ARRAY_LEN(PATCH_7_WRITES)},
    {"patch_range_8", 0x285ac, 4, "a883b9c4475398a5852aaf4ef0b4cbd8bd0557c4206c4d8bafd69832c8d56a47", "a828ca69c6e94a3592c35b9989123858720ac9b114514e040d53a604f87e1d6d", PATCH_8_WRITES, ARRAY_LEN(PATCH_8_WRITES)},
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

static int patch_range_matches(
    const unsigned char *data,
    size_t len,
    const struct binary_patch *patch,
    const char *expected_sha256
)
{
    char digest[C300X_INHOUSE_PATCH_HASH_LEN];

    if (patch->offset + patch->range_len > len) {
        return 0;
    }
    if (!c300x_sha256_bytes_hex(data + patch->offset, patch->range_len, digest, sizeof(digest))) {
        return 0;
    }
    return strcmp(digest, expected_sha256) == 0;
}

static int all_patch_ranges_match(
    const unsigned char *data,
    size_t len,
    int patched
)
{
    for (size_t index = 0; index < ARRAY_LEN(PATCHES); index++) {
        const struct binary_patch *patch = &PATCHES[index];
        const char *expected_sha256 = patched
            ? patch->patched_range_sha256
            : patch->expected_range_sha256;

        if (!patch_range_matches(data, len, patch, expected_sha256)) {
            return 0;
        }
    }
    return 1;
}

int c300x_inhouse_binary_patch_read_status(
    struct c300x_inhouse_binary_patch_status *status
)
{
    char backup_path[C300X_MAX_PATH_LEN];
    char target_path[C300X_MAX_PATH_LEN];
    unsigned char *data = NULL;
    size_t len = 0;

    memset(status, 0, sizeof(*status));
    status->supported = 1;
    if (!device_patch_target_path(target_path, sizeof(target_path))) {
        c300x_copy_string(status->state, sizeof(status->state), "missing");
        set_status_error(status, "target_path_failed");
        return 0;
    }
    if (!device_patch_backup_path(backup_path, sizeof(backup_path))) {
        c300x_copy_string(status->state, sizeof(status->state), "missing");
        set_status_error(status, "backup_path_failed");
        return 0;
    }
    if (!c300x_sha256_file_hex(target_path, status->file_sha256, sizeof(status->file_sha256))) {
        c300x_copy_string(status->state, sizeof(status->state), "missing");
        set_status_error(status, "binary_missing");
        return 0;
    }
    if (access(backup_path, F_OK) == 0) {
        status->backup_present = 1;
        (void)c300x_sha256_file_hex(backup_path, status->backup_sha256, sizeof(status->backup_sha256));
    }
    if (strcmp(status->file_sha256, C300X_DEVICE_PATCH_STOCK_SHA256) == 0) {
        c300x_copy_string(status->state, sizeof(status->state), "stock");
        return 1;
    }
    if (!read_file(target_path, &data, &len)) {
        c300x_copy_string(status->state, sizeof(status->state), "unsupported");
        set_status_error(status, "binary_read_failed");
        return 0;
    }
    if (all_patch_ranges_match(data, len, 1)) {
        status->patched = 1;
        c300x_copy_string(status->state, sizeof(status->state), "patched");
        free(data);
        return 1;
    }
    if (all_patch_ranges_match(data, len, 0)) {
        c300x_copy_string(status->state, sizeof(status->state), "stock");
        free(data);
        return 1;
    }
    free(data);
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
    char backup_path[C300X_MAX_PATH_LEN];
    char target_path[C300X_MAX_PATH_LEN];
    char target_tmp_path[C300X_MAX_PATH_LEN];
    unsigned char *data = NULL;
    size_t len = 0;
    C300X_INHOUSE_STAT_STRUCT original_stat;
    mode_t original_mode;
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
    if (!device_patch_target_path(target_path, sizeof(target_path))) {
        set_error(error, error_len, "target_path_failed");
        return 0;
    }
    if (!device_patch_backup_path(backup_path, sizeof(backup_path))) {
        set_error(error, error_len, "backup_path_failed");
        return 0;
    }
    if (!device_patch_temp_path(target_tmp_path, sizeof(target_tmp_path), target_path)) {
        set_error(error, error_len, "target_tmp_path_failed");
        return 0;
    }
    if (inhouse_stat_path(target_path, &original_stat) != 0) {
        set_error(error, error_len, "binary_stat_failed");
        return 0;
    }
    original_mode = (mode_t)(original_stat.st_mode & 07777);
    if (!status->backup_present && !copy_file_exact(target_path, backup_path, original_mode)) {
        set_error(error, error_len, "binary_backup_failed");
        return 0;
    }
    if (!read_file(target_path, &data, &len)) {
        set_error(error, error_len, "binary_read_failed");
        return 0;
    }
    for (size_t index = 0; index < sizeof(PATCHES) / sizeof(PATCHES[0]); index++) {
        const struct binary_patch *patch = &PATCHES[index];
        if (!patch_range_matches(data, len, patch, patch->expected_range_sha256)) {
            free(data);
            set_error(error, error_len, patch->name);
            return 0;
        }
        for (size_t write_index = 0; write_index < patch->write_count; write_index++) {
            const struct binary_write *write = &patch->writes[write_index];
            if (write->offset + write->len > patch->range_len) {
                free(data);
                set_error(error, error_len, patch->name);
                return 0;
            }
            memcpy(data + patch->offset + write->offset, write->data, write->len);
        }
        if (!patch_range_matches(data, len, patch, patch->patched_range_sha256)) {
            free(data);
            set_error(error, error_len, patch->name);
            return 0;
        }
    }
    if (!remount_root("rw")) {
        free(data);
        set_error(error, error_len, "remount_rw_failed");
        return 0;
    }
    fp = fopen(target_tmp_path, "wb");
    if (fp == NULL || fwrite(data, 1, len, fp) != len) {
        if (fp != NULL) {
            fclose(fp);
        }
        unlink(target_tmp_path);
        (void)remount_root("ro");
        free(data);
        set_error(error, error_len, "binary_write_failed");
        return 0;
    }
    free(data);
    (void)fsync(fileno(fp));
    if (
        fclose(fp) != 0
        || chmod(target_tmp_path, original_mode) != 0
        || (chown(target_tmp_path, original_stat.st_uid, original_stat.st_gid) != 0 && errno != EPERM)
        || rename(target_tmp_path, target_path) != 0
    ) {
        unlink(target_tmp_path);
        (void)remount_root("ro");
        set_error(error, error_len, "binary_replace_failed");
        return 0;
    }
    if (!remount_root_ro_or_error(error, error_len)) {
        return 0;
    }
    if (!c300x_inhouse_binary_patch_read_status(status) || !status->patched) {
        set_error(error, error_len, "patched_ranges_mismatch");
        return 0;
    }
    return 1;
}

int c300x_inhouse_binary_patch_restore(
    struct c300x_inhouse_binary_patch_status *status,
    char *error,
    size_t error_len
)
{
    char backup_path[C300X_MAX_PATH_LEN];
    char target_path[C300X_MAX_PATH_LEN];
    C300X_INHOUSE_STAT_STRUCT backup_stat;
    mode_t backup_mode;

    if (!device_patch_target_path(target_path, sizeof(target_path))) {
        set_error(error, error_len, "target_path_failed");
        return 0;
    }
    if (!device_patch_backup_path(backup_path, sizeof(backup_path))) {
        set_error(error, error_len, "backup_path_failed");
        return 0;
    }
    if (access(backup_path, F_OK) != 0) {
        set_error(error, error_len, "binary_backup_missing");
        return 0;
    }
    if (inhouse_stat_path(backup_path, &backup_stat) != 0) {
        set_error(error, error_len, "binary_backup_stat_failed");
        return 0;
    }
    backup_mode = (mode_t)(backup_stat.st_mode & 07777);
    if (!remount_root("rw")) {
        set_error(error, error_len, "remount_rw_failed");
        return 0;
    }
    if (!copy_file_exact(backup_path, target_path, backup_mode)) {
        (void)remount_root("ro");
        set_error(error, error_len, "binary_restore_failed");
        return 0;
    }
    if (!remount_root_ro_or_error(error, error_len)) {
        return 0;
    }
    return c300x_inhouse_binary_patch_read_status(status);
}
