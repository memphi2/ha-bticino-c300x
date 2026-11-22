#ifdef __arm__
#define _LARGEFILE64_SOURCE 1
#endif

#include "camera_running.h"

#include "c300x_agent.h"
#include "camera_files.h"
#include "media_geometry_patch.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <unistd.h>

#ifdef __arm__
typedef struct stat64 file_stat;
static int path_stat(const char *path, file_stat *st) { return (int)syscall(SYS_stat64, path, st); }
static int fd_stat(int fd, file_stat *st) { return (int)syscall(SYS_fstat64, fd, st); }
#else
typedef struct stat file_stat;
static int path_stat(const char *path, file_stat *st) { return stat(path, st); }
static int fd_stat(int fd, file_stat *st) { return fstat(fd, st); }
#endif

struct media_process {
    long pid;
    unsigned long long start;
    int geometry;
};

static char boot[64];
static struct media_process original;
static int baseline_geometry = C300X_MEDIA_GEOMETRY_UNKNOWN;
static int invalidated;
static int note_persisted;

static const char *env_or(const char *name, const char *fallback)
{
    const char *value = getenv(name);
    return value != NULL && value[0] != '\0' ? value : fallback;
}

static int process_start(long pid, unsigned long long *start)
{
    char path[64], line[4096];
    snprintf(path, sizeof(path), "/proc/%ld/stat", pid);
    FILE *fp = fopen(path, "r");
    if (fp == NULL) return 0;
    int ok = fgets(line, sizeof(line), fp) != NULL;
    fclose(fp);
    if (!ok) return 0;
    /* comm may contain spaces and parentheses; starttime is field 22. */
    char *field = strrchr(line, ')');
    if (field == NULL || field[1] != ' ') return 0;
    field += 2;
    for (int index = 3; index < 22; index++) {
        field = strchr(field, ' ');
        if (field == NULL) return 0;
        field++;
    }
    if (*field < '0' || *field > '9') return 0;
    char *end;
    errno = 0;
    *start = strtoull(field, &end, 10);
    return errno == 0 && *start > 0 && (*end == ' ' || *end == '\n');
}

static struct media_process process_now(void)
{
    struct media_process result = {0, 0, C300X_MEDIA_GEOMETRY_UNKNOWN};
    const char *override = getenv("C300X_MEDIA_GEOMETRY_RUNNING_TARGET");
    if (override != NULL && override[0] != '\0') {
        /* The existing offline executable fixture uses its inode as generation. */
        file_stat before, after;
        if (path_stat(override, &before) != 0) return result;
        int geometry = c300x_media_geometry_state(override);
        if (path_stat(override, &after) == 0 && before.st_dev == after.st_dev && before.st_ino == after.st_ino) {
            result.pid = 1;
            result.start = (unsigned long long)before.st_ino;
            result.geometry = geometry;
        }
        return result;
    }
    char wanted[32];
    if (!c300x_media_geometry_process_name(wanted, sizeof(wanted))) return result;
    DIR *dir = opendir("/proc");
    struct dirent *entry;
    int found = 0;
    if (dir == NULL) return result;
    while ((entry = readdir(dir)) != NULL) {
        char path[64], name[32], *end;
        long pid = strtol(entry->d_name, &end, 10);
        if (*end != '\0' || pid <= 0 || pid > INT_MAX) continue;
        unsigned long long before, after;
        if (!process_start(pid, &before)) continue;
        snprintf(path, sizeof(path), "/proc/%ld/comm", pid);
        FILE *fp = fopen(path, "r");
        if (fp == NULL) continue;
        int matched = fgets(name, sizeof(name), fp) != NULL;
        if (matched) {
            name[strcspn(name, "\n")] = '\0';
            matched = strcmp(name, wanted) == 0;
        }
        fclose(fp);
        if (!matched) continue;
        if (found++) {
            result = (struct media_process){0, 0, C300X_MEDIA_GEOMETRY_UNKNOWN};
            break;
        }
        int geometry = c300x_media_geometry_running_state((pid_t)pid);
        if (process_start(pid, &after) && before == after)
            result = (struct media_process){pid, before, geometry};
    }
    closedir(dir);
    return result;
}

int c300x_camera_running_current_geometry(void)
{
    return process_now().geometry;
}

static int write_note(const struct c300x_camera_values *v)
{
    char temp[C300X_MAX_PATH_LEN];
    const char *note = env_or("C300X_CAMERA_RUNNING_NOTE", "/tmp/c300x-camera-running");
    note_persisted = 0;
    if (boot[0] == '\0' || v->bitrate_kbps <= 0
        || snprintf(temp, sizeof(temp), "%s.XXXXXX", note) >= (int)sizeof(temp)) return 0;
    int fd = mkstemp(temp);
    if (fd < 0) return 0;
    if (fcntl(fd, F_SETFD, FD_CLOEXEC) != 0) { close(fd); unlink(temp); return 0; }
    FILE *fp = fdopen(fd, "w");
    if (fp == NULL) { close(fd); unlink(temp); return 0; }
    /* Keep the first nine fields readable by earlier agents. */
    int ok = fprintf(fp, "%s %d %d %d %d %d %d %d %d g1 %ld %llu %d %d %d\n", boot,
        v->bitrate_kbps, v->fps, v->width, v->height, v->crop[0], v->crop[1], v->crop[2], v->crop[3],
        original.pid, original.start, original.geometry, baseline_geometry, invalidated) > 0;
    ok = fflush(fp) == 0 && ok;
    if (ok) ok = fsync(fd) == 0;
    ok = fclose(fp) == 0 && ok;
    if (!ok || rename(temp, note) != 0) { unlink(temp); return 0; }
    note_persisted = 1;
    return 1;
}

int c300x_camera_running_prepare(const struct c300x_camera_values *baseline, const char **error)
{
    *error = "running_note_write_failed";
    if (!write_note(baseline)) return 0;
    *error = "";
    return 1;
}

static FILE *read_note(const char *note)
{
    int fd = open(note, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return NULL;
    file_stat st;
    /* Earlier notes were 0644. Accept those, but never another user's data or
     * a shared writable inode. Newly written notes are private (mkstemp 0600). */
    if (fd_stat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_nlink != 1
        || st.st_uid != geteuid() || (st.st_mode & 0022)) {
        close(fd);
        return NULL;
    }
    FILE *fp = fdopen(fd, "r");
    if (fp == NULL) close(fd);
    return fp;
}

void c300x_camera_running_load(int low, const char *settings, const char *crop,
    struct c300x_camera_values *values)
{
    char noted[64] = "";
    const char *note = env_or("C300X_CAMERA_RUNNING_NOTE", "/tmp/c300x-camera-running");
    FILE *fp = fopen(env_or("C300X_BOOT_ID_FILE", "/proc/sys/kernel/random/boot_id"), "r");
    struct c300x_camera_values v = {0};

    boot[0] = '\0';
    note_persisted = 0;
    original = process_now();
    int disk_geometry = low ? C300X_MEDIA_GEOMETRY_UNKNOWN : c300x_media_geometry_state(NULL);
    baseline_geometry = low || original.geometry == C300X_MEDIA_GEOMETRY_UNKNOWN
        ? disk_geometry : original.geometry;
    invalidated = !low && disk_geometry != C300X_MEDIA_GEOMETRY_UNKNOWN
        && original.geometry != C300X_MEDIA_GEOMETRY_UNKNOWN && disk_geometry != original.geometry;

    if (fp != NULL) {
        if (fscanf(fp, "%63s", boot) != 1) boot[0] = '\0';
        fclose(fp);
    }
    if (boot[0] != '\0' && (fp = read_note(note)) != NULL) {
        int matched = fscanf(fp, "%63s %d %d %d %d %d %d %d %d", noted, &v.bitrate_kbps,
            &v.fps, &v.width, &v.height, &v.crop[0], &v.crop[1], &v.crop[2], &v.crop[3]) == 9
            && strcmp(noted, boot) == 0;
        if (matched && v.bitrate_kbps > 0 && v.fps > 0 && v.width > 0 && v.height > 0) {
            char version[8];
            struct media_process process;
            int reference, invalid;
            int extra = fscanf(fp, "%7s", version);
            if (extra == 1 && strcmp(version, "g1") == 0
                && fscanf(fp, "%ld %llu %d %d %d", &process.pid, &process.start,
                    &process.geometry, &reference, &invalid) == 5
                && process.pid >= 0 && process.pid <= INT_MAX
                && (process.pid == 0 || process.start > 0)
                && process.geometry >= -1 && process.geometry <= 1
                && reference >= -1 && reference <= 1 && (invalid == 0 || invalid == 1)) {
                original = process;
                baseline_geometry = reference;
                invalidated = invalid;
                note_persisted = 1;
            } else if (extra == 1 || (!low && disk_geometry != C300X_MEDIA_GEOMETRY_UNKNOWN)) {
                /* Old notes retain the pending configuration baseline, but cannot
                 * associate a supported patched executable with that configuration. */
                invalidated = 1;
                if (extra == 1) baseline_geometry = C300X_MEDIA_GEOMETRY_UNKNOWN;
            }
            fclose(fp);
            *values = v;
            if (!note_persisted) (void)write_note(&v);
            return;
        }
        fclose(fp);
    }
    if (!c300x_camera_files_read(low, settings, crop, &v)) return;
    *values = v;
    (void)write_note(&v);
}

int c300x_camera_running_read(int low, const struct c300x_camera_values *baseline,
    const struct c300x_camera_values *saved, int saved_geometry,
    struct c300x_camera_values *values, int *geometry)
{
    struct media_process now = process_now();
    memset(values, 0, sizeof(*values));
    *geometry = C300X_MEDIA_GEOMETRY_UNKNOWN;
    int pending = baseline->bitrate_kbps > 0 && memcmp(baseline, saved, sizeof(*baseline)) != 0;
    if (!low && baseline_geometry != C300X_MEDIA_GEOMETRY_UNKNOWN
        && saved_geometry != C300X_MEDIA_GEOMETRY_UNKNOWN && baseline_geometry != saved_geometry)
        pending = 1;
    if (!invalidated && original.pid == 0 && pending) {
        /* A later revert cannot prove what an unobserved daemon read meanwhile. */
        invalidated = 1;
        write_note(baseline);
    }
    /* Startup may precede the daemon. Associate its first observed generation
     * only while both saved baselines still agree; never rebind a lost generation. */
    if (!invalidated && original.pid == 0 && now.pid > 0 && baseline->bitrate_kbps > 0
        && !pending && saved_geometry == baseline_geometry && (low || now.geometry == saved_geometry)) {
        original = now;
        write_note(baseline);
    }
    if (!invalidated && original.pid > 0 && now.pid > 0
        && (original.pid != now.pid || original.start != now.start
            || (now.geometry != C300X_MEDIA_GEOMETRY_UNKNOWN && now.geometry != original.geometry))) {
        invalidated = 1;
        write_note(baseline);
    }
    if (note_persisted && !invalidated && original.pid > 0 && now.pid == original.pid && now.start == original.start
        && now.geometry == original.geometry
        && (low || saved_geometry == C300X_MEDIA_GEOMETRY_UNKNOWN
            || now.geometry != C300X_MEDIA_GEOMETRY_UNKNOWN)) {
        *values = *baseline;
        *geometry = now.geometry;
    }
    return pending;
}
