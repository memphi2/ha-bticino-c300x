#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#include "device_file.h"

#include "c300x_agent.h"

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

/* The target's old glibc (2.26) has no plain `stat` symbol; mirror the
 * device_routing.c portable stat64 syscall shim used across this agent. */
#ifdef __arm__
#define C300X_DEVICE_FILE_STAT struct stat64
#else
#define C300X_DEVICE_FILE_STAT struct stat
#endif

static int stat_path(const char *path, C300X_DEVICE_FILE_STAT *status) {
#ifdef __arm__
    return (int)syscall(SYS_stat64, path, status);
#else
    return stat(path, status);
#endif
}

static int no_remount(void) {
    const char *p = getenv("C300X_AUDIO_NO_REMOUNT");
    return p != NULL && strcmp(p, "1") == 0;
}

int c300x_device_file_mtime(const char *path, long long *mtime) {
    C300X_DEVICE_FILE_STAT st;
    if (stat_path(path, &st) != 0 || !S_ISREG(st.st_mode)) {
        return 0;
    }
    *mtime = (long long)st.st_mtime;
    return 1;
}

int c300x_device_file_remount(const char *mode) {
    char command[64];
    if (no_remount()) {
        return 1;
    }
    if (snprintf(command, sizeof(command), "mount -o remount,%s / >/dev/null 2>&1", mode)
        >= (int)sizeof(command)) {
        return 0;
    }
    return system(command) == 0;
}

int c300x_device_file_read(const char *path, char **data, size_t *len, mode_t *mode) {
    C300X_DEVICE_FILE_STAT st;
    FILE *fp;
    char *buffer;
    size_t got;

    if (stat_path(path, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size < 0
        || (size_t)st.st_size > C300X_DEVICE_FILE_MAX) {
        return 0;
    }
    fp = fopen(path, "rb");
    if (fp == NULL) {
        return 0;
    }
    buffer = malloc((size_t)st.st_size + 1);
    if (buffer == NULL) {
        fclose(fp);
        return 0;
    }
    got = fread(buffer, 1, (size_t)st.st_size, fp);
    fclose(fp);
    if (got != (size_t)st.st_size) {
        free(buffer);
        return 0;
    }
    buffer[got] = '\0';
    *data = buffer;
    *len = got;
    if (mode != NULL) {
        *mode = (mode_t)(st.st_mode & 07777);
    }
    return 1;
}

/* Write data to path atomically: write a sibling temp file, fsync it, then
 * rename it over the target. A mid-write failure (short fwrite, fsync error,
 * full partition, power loss) therefore leaves the ORIGINAL file intact instead
 * of a truncated/corrupt live config. When the target already exists we copy its
 * owner+mode onto the temp first (the rename gives a new inode), preserving what
 * the old in-place write kept for free; new targets (backup creation) get the
 * private mode and the caller sets it explicitly afterwards. */
int c300x_device_file_write(const char *path, const char *data, size_t len) {
    C300X_DEVICE_FILE_STAT st;
    int have_meta = stat_path(path, &st) == 0 && S_ISREG(st.st_mode);
    char tmp[C300X_MAX_PATH_LEN];
    FILE *fp;
    int fd;
    int ok = 1;

    if (snprintf(tmp, sizeof(tmp), "%s.tmp.XXXXXX", path) >= (int)sizeof(tmp)) {
        return 0;
    }
    fd = mkstemp(tmp);
    if (fd < 0) {
        return 0;
    }
    if (fcntl(fd, F_SETFD, FD_CLOEXEC) != 0) {
        close(fd);
        unlink(tmp);
        return 0;
    }
    fp = fdopen(fd, "wb");
    if (fp == NULL) {
        close(fd);
        unlink(tmp);
        return 0;
    }
    if (fwrite(data, 1, len, fp) != len) {
        ok = 0;
    }
    if (fflush(fp) != 0) {
        ok = 0;
    }
    if (ok && have_meta) {
        /* rename creates a new inode, so restore the original owner/mode */
        if (fchown(fd, st.st_uid, st.st_gid) != 0
            || fchmod(fd, st.st_mode & 07777) != 0) {
            ok = 0;
        }
    }
    if (ok && fsync(fd) != 0) {
        ok = 0;
    }
    if (fclose(fp) != 0) {
        ok = 0;
    }
    if (ok && rename(tmp, path) == 0) {
        return 1;
    }
    (void)unlink(tmp);
    return 0;
}

/* Copy source to dest preserving source mode; used for one-time backup and for
 * restore. Never overwrites an existing backup. */
int c300x_device_file_copy(const char *source, const char *dest) {
    char *data = NULL;
    size_t len = 0;
    mode_t mode = 0600;
    int ok;
    if (!c300x_device_file_read(source, &data, &len, &mode)) {
        return 0;
    }
    ok = c300x_device_file_write(dest, data, len);
    free(data);
    if (ok) {
        (void)chmod(dest, mode);
    }
    return ok;
}

int c300x_device_file_mkdir_p(const char *path) {
    char tmp[C300X_MAX_PATH_LEN];
    size_t len = strlen(path);
    char *p;
    if (len == 0 || len >= sizeof(tmp)) {
        return 0;
    }
    memcpy(tmp, path, len + 1);
    for (p = tmp + 1; *p != '\0'; p++) {
        if (*p == '/') {
            *p = '\0';
            if (mkdir(tmp, 0755) != 0 && errno != EEXIST) {
                return 0;
            }
            *p = '/';
        }
    }
    return mkdir(tmp, 0755) == 0 || errno == EEXIST;
}

int c300x_device_file_backup_once(const char *source, const char *dest) {
    if (access(dest, F_OK) == 0) {
        return 1;
    }
    return c300x_device_file_copy(source, dest);
}
