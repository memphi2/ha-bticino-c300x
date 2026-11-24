#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#include "device_file.h"
#include "root_mount.h"

#include "c300x_agent.h"

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

int c300x_device_file_remount(const char *mode) {
    if (no_remount()) {
        return 1;
    }
    return c300x_root_remount(mode);
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
 * owner+mode onto the temp first (the rename gives a new inode); a new target
 * gets new_mode on the temp. final_mode, when given, is then set on the temp
 * as well, so nothing is chmodded by name after the rename. */
static int write_file(const char *path, const char *data, size_t len, mode_t new_mode, const mode_t *final_mode) {
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
    if (ok && (have_meta ? fchown(fd, st.st_uid, st.st_gid) != 0 || fchmod(fd, st.st_mode & 07777) != 0
                         : fchmod(fd, new_mode) != 0)) {
        ok = 0;
    }
    if (ok && final_mode != NULL) {
        (void)fchmod(fd, *final_mode);
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

int c300x_device_file_write_mode(const char *path, const char *data, size_t len, mode_t new_mode) {
    return write_file(path, data, len, new_mode, NULL);
}

int c300x_device_file_write(const char *path, const char *data, size_t len) {
    return write_file(path, data, len, 0600, NULL);
}

/* Copy source to dest with the source's mode, set before the rename; used
 * for the one-time backup and for restore. */
int c300x_device_file_copy(const char *source, const char *dest) {
    char *data = NULL;
    size_t len = 0;
    mode_t mode = 0600;
    int ok = c300x_device_file_read(source, &data, &len, &mode) && write_file(dest, data, len, 0600, &mode);
    free(data);
    return ok;
}

int c300x_device_file_backup_once(const char *source, const char *dest) {
    if (access(dest, F_OK) == 0) {
        return 1;
    }
    return c300x_device_file_copy(source, dest);
}

const char *c300x_device_file_backup_dir(void) {
    const char *p = getenv("C300X_AUDIO_BACKUP_DIR");
    return (p != NULL && p[0] != '\0')
        ? p
        : "/home/bticino/cfg/extra/c300x-device-file-backups/original";
}

int c300x_device_file_backup_path(const char *name, char *out, size_t out_len) {
    int written = snprintf(out, out_len, "%s/%s", c300x_device_file_backup_dir(), name);
    return written >= 0 && written < (int)out_len;
}
