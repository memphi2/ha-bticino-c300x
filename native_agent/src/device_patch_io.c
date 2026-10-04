#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#define _POSIX_C_SOURCE 200809L

#include "device_patch_io.h"

#include "c300x_agent.h"
#include "sha256.h"
#include "string_util.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <sys/stat.h>
#include <unistd.h>

#ifdef __arm__
#define C300X_PATCH_STAT_STRUCT struct stat64
#else
#define C300X_PATCH_STAT_STRUCT struct stat
#endif

static int patch_stat_path(const char *path, C300X_PATCH_STAT_STRUCT *status)
{
#ifdef __arm__
    return (int)syscall(SYS_stat64, path, status);
#else
    return stat(path, status);
#endif
}

int c300x_patch_file_mode(
    const char *path,
    mode_t *mode,
    uid_t *uid,
    gid_t *gid
)
{
    C300X_PATCH_STAT_STRUCT st;

    if (patch_stat_path(path, &st) != 0) {
        return 0;
    }
    if (mode != NULL) {
        *mode = (mode_t)(st.st_mode & 07777);
    }
    if (uid != NULL) {
        *uid = st.st_uid;
    }
    if (gid != NULL) {
        *gid = st.st_gid;
    }
    return 1;
}

int c300x_patch_ensure_parent_dir(const char *path)
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

int c300x_patch_copy_file_exact(const char *source, const char *target, mode_t mode)
{
    char tmp_path[C300X_MAX_PATH_LEN];
    C300X_PATCH_STAT_STRUCT source_stat;
    FILE *in;
    FILE *out;
    int fd;
    unsigned char buffer[4096];
    size_t read_len;

    if (!c300x_patch_ensure_parent_dir(target)) {
        return 0;
    }
    if (snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", target) >= (int)sizeof(tmp_path)) {
        return 0;
    }
    if (patch_stat_path(source, &source_stat) != 0) {
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
    if (fd < 0 || fchmod(fd, mode) != 0) {
        fclose(out);
        unlink(tmp_path);
        return 0;
    }
    if (fchown(fd, source_stat.st_uid, source_stat.st_gid) != 0 && errno != EPERM) {
        fclose(out);
        unlink(tmp_path);
        return 0;
    }
    if (fflush(out) != 0 || fsync(fd) != 0) {
        fclose(out);
        unlink(tmp_path);
        return 0;
    }
    if (fclose(out) != 0) {
        unlink(tmp_path);
        return 0;
    }
    if (rename(tmp_path, target) != 0) {
        unlink(tmp_path);
        return 0;
    }
    return 1;
}

int c300x_patch_remount_root(const char *mode)
{
    char command[64];
    const char *skip = getenv("C300X_DEVICE_PATCH_NO_REMOUNT");
    int status;

    if (skip != NULL && skip[0] != '\0') {
        return 1;
    }
    if (snprintf(command, sizeof(command), "mount -o remount,%s / >/dev/null 2>&1", mode) >= (int)sizeof(command)) {
        return 0;
    }
    status = system(command);
    return status == 0;
}

int c300x_patch_read_file(const char *path, unsigned char **data, size_t *len)
{
    C300X_PATCH_STAT_STRUCT st;
    FILE *fp;
    size_t read_len;

    *data = NULL;
    *len = 0;
    if (patch_stat_path(path, &st) != 0 || st.st_size <= 0) {
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

int c300x_patch_range_matches(
    const unsigned char *data,
    size_t len,
    const struct c300x_patch_range *patch,
    const char *expected_sha256
)
{
    char digest[65];

    if (patch->offset + patch->range_len > len) {
        return 0;
    }
    if (!c300x_sha256_bytes_hex(data + patch->offset, patch->range_len, digest, sizeof(digest))) {
        return 0;
    }
    return strcmp(digest, expected_sha256) == 0;
}
