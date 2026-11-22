#ifdef __arm__
#define _LARGEFILE64_SOURCE 1
#endif
#define _POSIX_C_SOURCE 200809L

#include "media_geometry_patch.h"
#include "c300x_agent.h"
#include "device_patch_io.h"
#include "sha256.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <unistd.h>

#define IMAGE_SIZE 186932
#define PATH_SIZE C300X_MAX_PATH_LEN
/* Independently implemented lifecycle code; only identification hashes and the
 * two instruction sites are firmware-specific. No vendor executable is bundled. */
#ifndef C300X_MEDIA_GEOMETRY_STOCK_SHA256
#define C300X_MEDIA_GEOMETRY_STOCK_SHA256 "97b61ad80e67c1b3ea494956568645b93c7fe3ef359f77af9c7e2ad6dff1bf9e"
#endif
#ifndef C300X_MEDIA_GEOMETRY_PATCHED_SHA256
#define C300X_MEDIA_GEOMETRY_PATCHED_SHA256 "baac8d478db5c4ae1baa46da963b379941d2952cfe047f3030b6a3182579821c"
#endif
#ifndef C300X_MEDIA_GEOMETRY_STOCK_SHA256_2_0_2
#define C300X_MEDIA_GEOMETRY_STOCK_SHA256_2_0_2 "e08227abb4bbc8ec47cdb6a2cf875c1b32c70ad0a295482b5ee7d73672b7479b"
#endif
#ifndef C300X_MEDIA_GEOMETRY_PATCHED_SHA256_2_0_2
#define C300X_MEDIA_GEOMETRY_PATCHED_SHA256_2_0_2 "b8b278f801284f8e573700554054e886e5ab256c08f09a609c15bdff2bb73e1d"
#endif
#ifndef C300X_MEDIA_GEOMETRY_TARGET_DIR
#define C300X_MEDIA_GEOMETRY_TARGET_DIR "/home/bticino/bin"
#endif
#ifndef C300X_MEDIA_GEOMETRY_BACKUP_DIR
#define C300X_MEDIA_GEOMETRY_BACKUP_DIR "/home/bticino/cfg/extra/c300x-device-file-backups/original/home/bticino/bin"
#endif
#ifdef __arm__
typedef struct stat64 file_stat;
static int fd_stat(int fd, file_stat *st) { return (int)syscall(SYS_fstat64, fd, st); }
#else
typedef struct stat file_stat;
static int fd_stat(int fd, file_stat *st) { return fstat(fd, st); }
#endif

int c300x_media_geometry_process_name(char *buf, size_t len)
{
    static const char mask[] = "b?_a?_m?d?a";
    static const struct { size_t offset; char value; } letters[] = {
        {1, 't'}, {4, 'v'}, {7, 'e'}, {9, 'i'}
    };
    if (!buf || len < sizeof(mask)) return 0;
    memcpy(buf, mask, sizeof(mask));
    for (size_t i = 0; i < sizeof(letters) / sizeof(letters[0]); i++) buf[letters[i].offset] = letters[i].value;
    return 1;
}

static const char *media_path(int backup, char out[PATH_SIZE])
{
    const char *p = getenv(backup ? "C300X_MEDIA_GEOMETRY_BACKUP" : "C300X_MEDIA_GEOMETRY_TARGET");
    char name[32];
    if (p && *p) return p;
    if (!c300x_media_geometry_process_name(name, sizeof(name))) return NULL;
    const char *root = backup ? getenv("C300X_AUDIO_BACKUP_DIR") : NULL;
    int written = root && *root
        ? snprintf(out, PATH_SIZE, "%s/home/bticino/bin/%s", root, name)
        : snprintf(out, PATH_SIZE, "%s/%s", backup
            ? C300X_MEDIA_GEOMETRY_BACKUP_DIR : C300X_MEDIA_GEOMETRY_TARGET_DIR, name);
    return written >= 0 && written < PATH_SIZE ? out : NULL;
}

/* Walk with directory descriptors so no component can redirect through a symlink. */
static int parent_dir(const char *path, char name[PATH_SIZE], int create)
{
    char copy[PATH_SIZE], *part, *next;
    int dir;
    if (!path || path[0] != '/' || strlen(path) >= sizeof(copy)) { errno = EINVAL; return -1; }
    strcpy(copy, path + 1);
    dir = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (dir < 0) return -1;
    part = copy;
    for (;;) {
        next = strchr(part, '/');
        if (next) *next = '\0';
        if (!*part || !strcmp(part, ".") || !strcmp(part, "..")) { errno = EINVAL; break; }
        if (!next) { strcpy(name, part); return dir; }
        int child = openat(dir, part, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (child < 0 && errno == ENOENT && create) {
            if (mkdirat(dir, part, 0755) != 0 && errno != EEXIST) break;
            if (fsync(dir) != 0) break;
            child = openat(dir, part, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        }
        if (child < 0) break;
        close(dir);
        dir = child;
        part = next + 1;
    }
    int saved = errno;
    close(dir);
    errno = saved;
    return -1;
}

static int read_fd(int fd, unsigned char *data, file_stat *st)
{
    size_t used = 0;
    if (fd_stat(fd, st) || !S_ISREG(st->st_mode) || st->st_size != IMAGE_SIZE) return 0;
    while (used < IMAGE_SIZE) {
        ssize_t n = read(fd, data + used, IMAGE_SIZE - used);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return 0;
        used += (size_t)n;
    }
    unsigned char extra;
    return read(fd, &extra, 1) == 0;
}

static int read_at(int dir, const char *name, unsigned char *data, file_stat *st)
{
    int fd = openat(dir, name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return 0;
    int ok = read_fd(fd, data, st) && st->st_nlink == 1;
    close(fd);
    return ok;
}

/* Identity retains the exact variant: even=stock, following odd=its patch.
 * Build IDs and all other bytes participate in the hash; nothing is normalized. */
static int identify(const unsigned char *data)
{
    static const struct { const char *stock; const char *patched; } variants[] = {
        {C300X_MEDIA_GEOMETRY_STOCK_SHA256, C300X_MEDIA_GEOMETRY_PATCHED_SHA256},
        {C300X_MEDIA_GEOMETRY_STOCK_SHA256_2_0_2, C300X_MEDIA_GEOMETRY_PATCHED_SHA256_2_0_2}
    };
    char hash[65];
    if (!c300x_sha256_bytes_hex(data, IMAGE_SIZE, hash, sizeof(hash))) return C300X_MEDIA_GEOMETRY_UNKNOWN;
    for (size_t i = 0; i < sizeof(variants) / sizeof(variants[0]); i++) {
        if (!strcmp(hash, variants[i].stock)) return (int)i * 2;
        if (!strcmp(hash, variants[i].patched)) return (int)i * 2 + 1;
    }
    return C300X_MEDIA_GEOMETRY_UNKNOWN;
}

static enum c300x_media_geometry_state classify(const unsigned char *data)
{
    int identity = identify(data);
    return identity < 0 ? C300X_MEDIA_GEOMETRY_UNKNOWN : identity % 2;
}

enum c300x_media_geometry_state c300x_media_geometry_state(const char *path)
{
    char name[PATH_SIZE], default_path[PATH_SIZE];
    file_stat st;
    unsigned char *data = malloc(IMAGE_SIZE);
    int dir = parent_dir(path ? path : media_path(0, default_path), name, 0);
    enum c300x_media_geometry_state state = C300X_MEDIA_GEOMETRY_UNKNOWN;
    if (data && dir >= 0 && read_at(dir, name, data, &st)) state = classify(data);
    if (dir >= 0) close(dir);
    free(data);
    return state;
}

enum c300x_media_geometry_state c300x_media_geometry_running_state(pid_t pid)
{
    char path[64];
    file_stat st;
    enum c300x_media_geometry_state state = C300X_MEDIA_GEOMETRY_UNKNOWN;
    if (pid <= 0) return state;
    snprintf(path, sizeof(path), "/proc/%ld/exe", (long)pid);
    /* This kernel-provided symlink is intentional; deleted executables have nlink=0. */
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    unsigned char *data = malloc(IMAGE_SIZE);
    if (fd >= 0 && data && read_fd(fd, data, &st)) state = classify(data);
    if (fd >= 0) close(fd);
    free(data);
    return state;
}

static void patch_words(unsigned char *data)
{
    static const unsigned char width_r7[] = {0x0f, 0x7d, 0xa0, 0xe3};
    static const unsigned char width_r5[] = {0x0f, 0x5d, 0xa0, 0xe3};
    static const struct c300x_patch_write writes[] = {
        {0x14a24, width_r7, sizeof(width_r7)}, {0x14de4, width_r5, sizeof(width_r5)}
    };
    for (size_t i = 0; i < sizeof(writes) / sizeof(writes[0]); i++)
        memcpy(data + writes[i].offset, writes[i].data, writes[i].len);
}

static int lock_backup(int dir)
{
    file_stat st;
    if (fd_stat(dir, &st)) return -1;
    if (st.st_uid != geteuid() || (st.st_mode & 0022)) { errno = EINVAL; return -1; }
    int fd = openat(dir, ".geometry.lock", O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    if (fd_stat(fd, &st) || !S_ISREG(st.st_mode) || st.st_nlink != 1
        || st.st_uid != geteuid() || (st.st_mode & 0077)) {
        close(fd);
        errno = EINVAL;
        return -1;
    }
    if (flock(fd, LOCK_EX | LOCK_NB)) {
        int saved = errno;
        close(fd);
        errno = saved;
        return -1;
    }
    return fd;
}

/* Publish only a completely written, hashed and synced inode. Backups never overwrite. */
static int publish(int dir, const char *name, const unsigned char *data,
    const file_stat *meta, int backup, int expected)
{
    char temp[80];
    int fd = -1, ok = 0;
    for (unsigned i = 0; i < 100; i++) {
        snprintf(temp, sizeof(temp), ".geometry.%ld.%u.tmp", (long)getpid(), i);
        fd = openat(dir, temp, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (fd >= 0 || errno != EEXIST) break;
    }
    if (fd < 0) return 0;
    size_t used = 0;
    while (used < IMAGE_SIZE) {
        ssize_t n = write(fd, data + used, IMAGE_SIZE - used);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) goto done;
        used += (size_t)n;
    }
    if (fchown(fd, meta->st_uid, meta->st_gid)
        || fchmod(fd, meta->st_mode & 07777) || fsync(fd)) goto done;
    unsigned char *check = malloc(IMAGE_SIZE);
    file_stat st;
    ok = check && lseek(fd, 0, SEEK_SET) == 0 && read_fd(fd, check, &st) && identify(check) == expected;
    free(check);
    if (!ok) goto done;
    ok = 0;
    if (close(fd)) { fd = -1; goto done; }
    fd = -1;
    if (backup) {
        if (linkat(dir, temp, dir, name, 0)) goto done;
        if (unlinkat(dir, temp, 0)) goto done;
    } else if (renameat(dir, temp, dir, name)) goto done;
    ok = fsync(dir) == 0;
done:
    if (fd >= 0) close(fd);
    unlinkat(dir, temp, 0);
    return ok;
}

/* Returns 1 only for a genuinely absent path, not dangling symlinks or unreadable files. */
static int backup_absent(void)
{
    char name[PATH_SIZE], path[PATH_SIZE];
    int dir = parent_dir(media_path(1, path), name, 0);
    if (dir < 0) return errno == ENOENT;
    int fd = openat(dir, name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    int absent = fd < 0 && errno == ENOENT;
    if (fd >= 0) close(fd);
    close(dir);
    return absent;
}

static int target_regular_or_absent(void)
{
    char name[PATH_SIZE], path[PATH_SIZE];
    file_stat st;
    int dir = parent_dir(media_path(0, path), name, 0);
    if (dir < 0) return errno == ENOENT;
    int fd = openat(dir, name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    int ok = fd < 0 ? errno == ENOENT : !fd_stat(fd, &st) && S_ISREG(st.st_mode) && st.st_nlink == 1;
    if (fd >= 0) close(fd);
    close(dir);
    return ok;
}

static int operate(int enable, int prepare, int *ro_failed, const char **error)
{
    char target_name[PATH_SIZE], backup_name[PATH_SIZE], path[PATH_SIZE];
    int target = -1, backup = -1, lock = -1, ok = 0, remounted = 0;
    unsigned char *data = NULL, *saved = NULL;
    file_stat meta, backup_meta;
    *error = "";
    *ro_failed = 0;
    if (enable != 0 && enable != 1) { *error = "invalid_geometry"; return 0; }
    *error = "geometry_target_invalid";
    target = parent_dir(media_path(0, path), target_name, 0);
    data = malloc(IMAGE_SIZE);
    saved = malloc(IMAGE_SIZE);
    if (target < 0 || !data || !saved || !read_at(target, target_name, data, &meta)) goto done;
    int identity = identify(data);
    if (identity < 0) goto done;
    int state = identity % 2, stock_identity = identity - state;
    *error = "geometry_backup_invalid";
    backup = parent_dir(media_path(1, path), backup_name, prepare);
    if (backup < 0) goto done;
    if ((lock = lock_backup(backup)) < 0) {
        if (errno == EWOULDBLOCK || errno == EAGAIN) *error = "geometry_busy";
        goto done;
    }
    /* A valid existing backup is required, even for no-op apply. */
    if (!read_at(backup, backup_name, saved, &backup_meta)) {
        if (!prepare || !backup_absent()) goto done;
        if (state != C300X_MEDIA_GEOMETRY_STOCK) { *error = "geometry_backup_missing"; goto done; }
        memcpy(saved, data, IMAGE_SIZE);
        if (identify(saved) != stock_identity
            || !publish(backup, backup_name, saved, &meta, 1, stock_identity)
            || !read_at(backup, backup_name, saved, &backup_meta)) goto done;
    }
    if (identify(saved) != stock_identity || backup_meta.st_uid != meta.st_uid
        || backup_meta.st_gid != meta.st_gid || (backup_meta.st_mode & 0022)) goto done;
    if (prepare || state == enable) { ok = 1; goto done; }
    if (enable) patch_words(saved);
    if (identify(saved) != stock_identity + enable) { *error = "geometry_patch_hash_mismatch"; goto done; }
    *error = "remount_rw_failed";
    if (!c300x_patch_remount_root("rw")) goto done;
    remounted = 1;
    *error = "geometry_target_changed";
    file_stat current;
    if (!read_at(target, target_name, data, &current) || identify(data) != identity
        || current.st_dev != meta.st_dev || current.st_ino != meta.st_ino
        || current.st_mode != meta.st_mode || current.st_uid != meta.st_uid || current.st_gid != meta.st_gid) goto done;
    *error = "geometry_write_failed";
    if (!publish(target, target_name, saved, &meta, 0, stock_identity + enable)) goto done;
    *error = "geometry_readback_failed";
    if (!read_at(target, target_name, data, &current) || identify(data) != stock_identity + enable) goto done;
    ok = 1;
done:
    if (remounted) *ro_failed = !c300x_patch_remount_root("ro");
    if (lock >= 0) close(lock);
    if (backup >= 0) close(backup);
    if (target >= 0) close(target);
    free(data);
    free(saved);
    if (ok) *error = "";
    return ok;
}

int c300x_media_geometry_prepare(int enable, const char **error)
{
    int ro_failed;
    return operate(enable, 1, &ro_failed, error);
}

int c300x_media_geometry_apply(int enable, int *ro_failed, const char **error)
{
    return operate(enable, 0, ro_failed, error);
}

int c300x_media_geometry_restore(int *ro_failed, const char **error)
{
    *ro_failed = 0;
    *error = "";
    if (c300x_media_geometry_state(NULL) != C300X_MEDIA_GEOMETRY_PATCHED
        && target_regular_or_absent() && backup_absent()) return 1;
    return c300x_media_geometry_prepare(0, error) && c300x_media_geometry_apply(0, ro_failed, error);
}
