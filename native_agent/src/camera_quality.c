#include "camera_quality.h"

#include "c300x_agent.h"
#include "device_file.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* What the device started with; zero while not known. */
static struct c300x_camera_values running;

static const char *env_or(const char *name, const char *fallback)
{
    const char *value = getenv(name);
    return (value != NULL && value[0] != '\0') ? value : fallback;
}

static const char *settings_path(void)
{
    return env_or("C300X_CAMERA_QUALITY_FILE", "/home/bticino/cfg/bt_answering_machine");
}

/* Firmware 3.0.x, the one with the Qt 5 display, sends only the low stream. */
static int low_stream(void)
{
    return c300x_device_display_is_qt5();
}

int c300x_camera_quality_read_values(const char *path, int low, struct c300x_camera_values *values)
{
    char *data = NULL;
    size_t len = 0;
    int ok;

    if (!c300x_device_file_read(path, &data, &len, NULL)) {
        return 0;
    }
    ok = strlen(data) == len && c300x_camera_settings_parse(data, low, values);
    free(data);
    return ok;
}

void c300x_camera_quality_note_running(void)
{
    struct c300x_camera_values values;

    if (c300x_camera_running_values(settings_path(), low_stream(), &values)) {
        running = values;
    }
}

int c300x_camera_quality_read(struct c300x_camera_quality *quality)
{
    memset(quality, 0, sizeof(*quality));
    quality->low = low_stream();
    quality->running = running;
    c300x_camera_quality_size_name(quality->low, &running, quality->running_size,
        sizeof(quality->running_size));
    if (!c300x_camera_quality_read_values(settings_path(), quality->low, &quality->saved)) {
        return 0;
    }
    quality->supported = 1;
    c300x_camera_quality_size_name(quality->low, &quality->saved, quality->size, sizeof(quality->size));
    quality->restart_required = running.bitrate_kbps > 0
        && memcmp(&running, &quality->saved, sizeof(running)) != 0;
    return 1;
}

int c300x_camera_quality_status(struct c300x_camera_quality *quality, int video_enabled)
{
    if (c300x_camera_quality_read(quality) && video_enabled) {
        return 1;
    }
    int low = quality->low; /* the stream stays named */
    memset(quality, 0, sizeof(*quality));
    quality->low = low;
    return 0;
}

/* Writes the values of one stream, keeping everything else of the file. */
static int write_values(struct c300x_camera_quality *quality, int low, const struct c300x_camera_values *values,
    const char **error)
{
    char backup[C300X_MAX_PATH_LEN];
    struct c300x_camera_values check;
    char *data = NULL;
    size_t len = 0;
    int ok, ro_failed;

    *error = "read_failed";
    if (!c300x_device_file_backup_path("bt_answering_machine", backup, sizeof(backup))
        || !c300x_device_file_read(settings_path(), &data, &len, NULL)) {
        return 0;
    }
    if (strlen(data) != len) {
        free(data);
        return 0;
    }
    if ((data = c300x_camera_settings_with(data, low, values)) == NULL) {
        return 0;
    }
    *error = "backup_failed";
    if (!c300x_device_file_mkdir_p(c300x_device_file_backup_dir())
        || !c300x_device_file_backup_once(settings_path(), backup)) {
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
    *error = ok ? "target_state_mismatch" : "write_failed";
    if (!c300x_camera_quality_read_values(settings_path(), low, &check)
        || memcmp(&check, values, sizeof(check)) != 0) {
        return 0;
    }
    (void)c300x_camera_quality_read(quality);
    quality->changed = ok;
    quality->remount_ro_failed = ro_failed;
    /* Not knowing what the device runs, only a restart makes the change count. */
    quality->restart_required |= ok && running.bitrate_kbps <= 0;
    return ok;
}

static int in_range(int value, int saved, int minimum, int maximum)
{
    /* A value the file already has may stay, even outside the range. */
    return value == saved || (value >= minimum && value <= maximum);
}

int c300x_camera_quality_apply(struct c300x_camera_quality *quality, int bitrate_kbps, int fps,
    const char *size, const char **error)
{
    struct c300x_camera_values target;
    const struct c300x_camera_limits *limits;

    *error = "unsupported";
    if (!c300x_camera_quality_read(quality)) {
        return 0;
    }
    limits = c300x_camera_quality_limits(quality->low);
    target = quality->saved;
    target.bitrate_kbps = bitrate_kbps;
    target.fps = fps;
    /* The size the file gives already stays as it is written there. */
    *error = "invalid_size";
    if (size != NULL && strcmp(size, quality->size) != 0
        && !c300x_camera_quality_size_values(quality->low, size, &target)) {
        return 0;
    }
    *error = "out_of_range";
    if (!in_range(bitrate_kbps, quality->saved.bitrate_kbps, limits->bitrate_min, limits->bitrate_max)
        || !in_range(fps, quality->saved.fps, limits->fps_min, limits->fps_max)) {
        return 0;
    }
    if (memcmp(&target, &quality->saved, sizeof(target)) == 0) {
        return 1;
    }
    return write_values(quality, quality->low, &target, error);
}

int c300x_camera_quality_remove_patches(const char **error)
{
    char backup[C300X_MAX_PATH_LEN];
    struct c300x_camera_quality quality;
    struct c300x_camera_values original, current;
    int found = 0;

    *error = "";
    if (!c300x_device_file_backup_path("bt_answering_machine", backup, sizeof(backup))
        || access(backup, F_OK) != 0) {
        return 1; /* never changed on this device */
    }
    /* Both streams: the firmware may have changed since the values were. */
    for (int low = 0; low < 2; low++) {
        if (!c300x_camera_quality_read_values(backup, low, &original)) {
            continue;
        }
        found = 1;
        /* A file the device replaced meanwhile (a firmware update) is not ours to change. */
        if (c300x_camera_quality_read_values(settings_path(), low, &current)
            && memcmp(&current, &original, sizeof(original)) != 0
            && !write_values(&quality, low, &original, error)) {
            return 0;
        }
    }
    *error = found ? "" : "backup_unreadable";
    return found;
}
