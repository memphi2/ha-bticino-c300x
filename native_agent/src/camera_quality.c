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

static int read_values(const char *path, struct c300x_camera_values *values)
{
    char *data = NULL;
    size_t len = 0;
    int ok;

    if (!c300x_device_file_read(path, &data, &len, NULL)) {
        return 0;
    }
    ok = strlen(data) == len && c300x_camera_settings_parse(data, low_stream(), values);
    free(data);
    return ok;
}

/* The values in the file when the device started. An agent that restarts
 * without the device finds them in a note that names the boot. */
void c300x_camera_quality_note_running(void)
{
    char boot[64] = "", noted[64] = "", temp[C300X_MAX_PATH_LEN];
    const char *note = env_or("C300X_CAMERA_RUNNING_NOTE", "/tmp/c300x-camera-running");
    FILE *fp = fopen(env_or("C300X_BOOT_ID_FILE", "/proc/sys/kernel/random/boot_id"), "r");
    struct c300x_camera_values v = {0};

    if (fp != NULL) {
        if (fscanf(fp, "%63s", boot) != 1) {
            boot[0] = '\0';
        }
        fclose(fp);
    }
    if (boot[0] != '\0' && (fp = fopen(note, "r")) != NULL) {
        int matched = fscanf(fp, "%63s %d %d %d %d", noted, &v.bitrate_kbps, &v.fps, &v.width, &v.height) == 5
            && strcmp(noted, boot) == 0;
        fclose(fp);
        if (matched && v.bitrate_kbps > 0 && v.fps > 0 && v.width > 0 && v.height > 0) {
            running = v;
            return;
        }
    }
    if (!read_values(settings_path(), &v)) {
        return;
    }
    running = v;
    /* A note cut short must not pass for the values the device runs. */
    if (boot[0] != '\0' && snprintf(temp, sizeof(temp), "%s.tmp", note) < (int)sizeof(temp)
        && (fp = fopen(temp, "w")) != NULL) {
        int ok = fprintf(fp, "%s %d %d %d %d\n", boot, v.bitrate_kbps, v.fps, v.width, v.height) > 0;
        ok = fclose(fp) == 0 && ok;
        if (!ok || rename(temp, note) != 0) {
            unlink(temp);
        }
    }
}

int c300x_camera_quality_read(struct c300x_camera_quality *quality)
{
    memset(quality, 0, sizeof(*quality));
    quality->low = low_stream();
    quality->running = running;
    c300x_camera_quality_size_name(quality->low, &running, quality->running_size,
        sizeof(quality->running_size));
    if (!read_values(settings_path(), &quality->saved)) {
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

/* Writes the values, keeping everything else of the file. */
static int write_values(struct c300x_camera_quality *quality, const struct c300x_camera_values *values,
    const char **error)
{
    char backup[C300X_MAX_PATH_LEN];
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
    if ((data = c300x_camera_settings_with(data, quality->low, values)) == NULL) {
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
    if (!c300x_camera_quality_read(quality) || memcmp(&quality->saved, values, sizeof(*values)) != 0) {
        return 0;
    }
    quality->changed = ok;
    quality->remount_ro_failed = ro_failed;
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
    /* Unreadable when the agent started: before its first change the file
     * holds what the device read, as the agent assumes at its start. */
    if (running.bitrate_kbps <= 0) {
        c300x_camera_quality_note_running();
    }
    return write_values(quality, &target, error);
}

int c300x_camera_quality_remove_patches(const char **error)
{
    char backup[C300X_MAX_PATH_LEN];
    struct c300x_camera_quality quality;
    struct c300x_camera_values original;

    *error = "";
    if (!c300x_device_file_backup_path("bt_answering_machine", backup, sizeof(backup))
        || access(backup, F_OK) != 0) {
        return 1; /* never changed on this device */
    }
    *error = "backup_unreadable";
    if (!read_values(backup, &original)) {
        return 0;
    }
    /* A file without the values (a firmware update) is left alone; the
     * factory values are the same on every firmware. */
    if (!c300x_camera_quality_read(&quality) || memcmp(&quality.saved, &original, sizeof(original)) == 0) {
        return 1;
    }
    return write_values(&quality, &original, error);
}
