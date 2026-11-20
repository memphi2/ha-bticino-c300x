#include "camera_quality.h"

#include "c300x_agent.h"
#include "device_file.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define SECTION "[Answering Machine]"
#define BITRATE_KEY "BitrateRtpH"
#define FPS_KEY "FpsRtpH"

static const char *settings_path(void)
{
    const char *path = getenv("C300X_CAMERA_QUALITY_FILE");
    return (path != NULL && path[0] != '\0') ? path : "/home/bticino/cfg/bt_answering_machine";
}

static int backup_path(char *out, size_t out_len, char *dir, size_t dir_len)
{
    const char *base = getenv("C300X_AUDIO_BACKUP_DIR");
    if (base == NULL || base[0] == '\0') {
        base = "/home/bticino/cfg/extra/c300x-device-file-backups/original";
    }
    return snprintf(dir, dir_len, "%s", base) < (int)dir_len
        && snprintf(out, out_len, "%s/bt_answering_machine", base) < (int)out_len;
}

/* The value of key in the section: where its digits start and end, or NULL. */
static const char *find_value(const char *data, const char *key, const char **end)
{
    const char *line = data;
    size_t key_len = strlen(key);
    int inside = 0;

    while (*line != '\0') {
        const char *next = strchr(line, '\n');
        size_t len = next != NULL ? (size_t)(next - line) : strlen(line);

        if (len > 0 && line[len - 1] == '\r') {
            len--;
        }
        if (line[0] == '[') {
            inside = len == strlen(SECTION) && strncmp(line, SECTION, len) == 0;
        } else if (inside && len > key_len + 1 && strncmp(line, key, key_len) == 0 && line[key_len] == '=') {
            const char *digits = line + key_len + 1, *stop = digits;
            while (stop < line + len && *stop >= '0' && *stop <= '9') {
                stop++;
            }
            if (stop == line + len && stop > digits && stop - digits <= 5) {
                *end = stop;
                return digits;
            }
            return NULL;
        }
        if (next == NULL) {
            break;
        }
        line = next + 1;
    }
    return NULL;
}

static int read_values(const char *path, int *bitrate, int *fps)
{
    char *data = NULL;
    size_t len = 0;
    const char *value, *end;
    int ok = 0;

    if (!c300x_device_file_read(path, &data, &len, NULL)) {
        return 0;
    }
    if (strlen(data) == len && (value = find_value(data, BITRATE_KEY, &end)) != NULL) {
        *bitrate = atoi(value);
        if ((value = find_value(data, FPS_KEY, &end)) != NULL) {
            *fps = atoi(value);
            ok = 1;
        }
    }
    free(data);
    return ok;
}

static int written_since_boot(const char *path)
{
    struct timespec now, up;
    long long mtime = 0;

    if (!c300x_device_file_mtime(path, &mtime)
        || clock_gettime(CLOCK_REALTIME, &now) != 0 || clock_gettime(CLOCK_MONOTONIC, &up) != 0) {
        return 0;
    }
    return mtime > (long long)now.tv_sec - (long long)up.tv_sec;
}

int c300x_camera_quality_read(struct c300x_camera_quality *quality)
{
    memset(quality, 0, sizeof(*quality));
    if (!read_values(settings_path(), &quality->bitrate_kbps, &quality->fps)) {
        return 0;
    }
    quality->supported = 1;
    quality->restart_required = written_since_boot(settings_path());
    return 1;
}

/* data with the digits of key replaced by value; NULL when it does not fit. */
static char *with_value(char *data, const char *key, int value)
{
    const char *end = NULL, *digits = find_value(data, key, &end);
    size_t before, size;
    char number[12];
    char *out;

    if (digits == NULL) {
        free(data);
        return NULL;
    }
    before = (size_t)(digits - data);
    snprintf(number, sizeof(number), "%d", value);
    size = before + strlen(number) + strlen(end) + 1;
    out = malloc(size);
    if (out != NULL) {
        memcpy(out, data, before);
        snprintf(out + before, size - before, "%s%s", number, end);
    }
    free(data);
    return out;
}

int c300x_camera_quality_apply(struct c300x_camera_quality *quality, int bitrate_kbps, int fps,
    const char **error)
{
    char backup[C300X_MAX_PATH_LEN], dir[C300X_MAX_PATH_LEN];
    char *data = NULL;
    size_t len = 0;
    int ok, ro_failed;

    *error = "unsupported";
    if (!c300x_camera_quality_read(quality)) {
        return 0;
    }
    if (bitrate_kbps == 0) bitrate_kbps = quality->bitrate_kbps;
    if (fps == 0) fps = quality->fps;
    *error = "out_of_range";
    if (bitrate_kbps < C300X_CAMERA_BITRATE_MIN || bitrate_kbps > C300X_CAMERA_BITRATE_MAX
        || fps < C300X_CAMERA_FPS_MIN || fps > C300X_CAMERA_FPS_MAX) {
        return 0;
    }
    if (bitrate_kbps == quality->bitrate_kbps && fps == quality->fps) {
        return 1;
    }
    *error = "read_failed";
    if (!backup_path(backup, sizeof(backup), dir, sizeof(dir))
        || !c300x_device_file_read(settings_path(), &data, &len, NULL)) {
        return 0;
    }
    data = with_value(data, BITRATE_KEY, bitrate_kbps);
    if (data != NULL) data = with_value(data, FPS_KEY, fps);
    if (data == NULL) {
        return 0;
    }
    *error = "backup_failed";
    if (!c300x_device_file_mkdir_p(dir) || !c300x_device_file_backup_once(settings_path(), backup)) {
        free(data);
        return 0;
    }
    *error = "remount_rw_failed";
    if (!c300x_device_file_remount("rw")) {
        free(data);
        return 0;
    }
    ok = c300x_device_file_write(settings_path(), data, strlen(data));
    free(data);
    /* A root that stays writable does not undo the write; the next start
     * mounts it read-only again. */
    ro_failed = !c300x_device_file_remount("ro");
    *error = "write_failed";
    if (!ok || !c300x_camera_quality_read(quality)
        || quality->bitrate_kbps != bitrate_kbps || quality->fps != fps) {
        return 0;
    }
    quality->changed = 1;
    quality->remount_ro_failed = ro_failed;
    return 1;
}

int c300x_camera_quality_remove_patches(const char **error)
{
    char backup[C300X_MAX_PATH_LEN], dir[C300X_MAX_PATH_LEN];
    struct c300x_camera_quality quality;
    int bitrate = 0, fps = 0;

    *error = "";
    if (!backup_path(backup, sizeof(backup), dir, sizeof(dir)) || access(backup, F_OK) != 0) {
        return 1; /* never changed on this device */
    }
    *error = "backup_unreadable";
    if (!read_values(backup, &bitrate, &fps)) {
        return 0;
    }
    return c300x_camera_quality_apply(&quality, bitrate, fps, error);
}

void c300x_camera_quality_body(const struct c300x_camera_quality *quality, char *body, size_t body_len)
{
    snprintf(body, body_len,
        "{\"ok\":true,\"supported\":%s,\"bitrate_kbps\":%d,\"fps\":%d,"
        "\"bitrate_min\":%d,\"bitrate_max\":%d,\"fps_min\":%d,\"fps_max\":%d,"
        "\"restart_required\":%s,\"changed\":%s,\"remount_ro_failed\":%s}\n",
        quality->supported ? "true" : "false", quality->bitrate_kbps, quality->fps,
        C300X_CAMERA_BITRATE_MIN, C300X_CAMERA_BITRATE_MAX, C300X_CAMERA_FPS_MIN, C300X_CAMERA_FPS_MAX,
        quality->restart_required ? "true" : "false", quality->changed ? "true" : "false",
        quality->remount_ro_failed ? "true" : "false");
}
