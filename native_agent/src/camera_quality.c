#include "camera_quality.h"

#include "c300x_agent.h"
#include "camera_files.h"
#include "device_detect.h"
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

/* The cut of the high stream; the device reads it at its start too. */
static const char *crop_path(void)
{
    return env_or("C300X_CAMERA_CROP_FILE", "/home/bticino/cfg/stack_open.xml");
}

/* C300X 3.0.x and the C100X send only the low stream. */
static int low_stream(void)
{
    return c300x_device_camera_resolution_fixed();
}

static int read_values(const char *path, const char *cut_path, struct c300x_camera_values *values)
{
    return c300x_camera_files_read(low_stream(), path, cut_path, values);
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
        int matched = fscanf(fp, "%63s %d %d %d %d %d %d %d %d", noted, &v.bitrate_kbps, &v.fps, &v.width,
            &v.height, &v.crop[0], &v.crop[1], &v.crop[2], &v.crop[3]) == 9 && strcmp(noted, boot) == 0;
        fclose(fp);
        if (matched && v.bitrate_kbps > 0 && v.fps > 0 && v.width > 0 && v.height > 0) {
            running = v;
            return;
        }
    }
    if (!read_values(settings_path(), crop_path(), &v)) {
        return;
    }
    running = v;
    /* A note cut short must not pass for the values the device runs. */
    if (boot[0] != '\0' && snprintf(temp, sizeof(temp), "%s.tmp", note) < (int)sizeof(temp)
        && (fp = fopen(temp, "w")) != NULL) {
        int ok = fprintf(fp, "%s %d %d %d %d %d %d %d %d\n", boot, v.bitrate_kbps, v.fps, v.width, v.height,
            v.crop[0], v.crop[1], v.crop[2], v.crop[3]) > 0;
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
    if (!read_values(settings_path(), crop_path(), &quality->saved)) {
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

/* Writes the values, keeping everything else of the files, and reads them back. */
static int write_values(struct c300x_camera_quality *quality, const struct c300x_camera_values *values,
    const char **error)
{
    struct c300x_camera_values now = quality->saved;
    int ro_failed = 0;

    if (!c300x_camera_files_write(quality->low, &now, values, settings_path(), crop_path(), &ro_failed, error)) {
        return 0;
    }
    *error = "target_state_mismatch";
    if (!c300x_camera_quality_read(quality) || memcmp(&quality->saved, values, sizeof(*values)) != 0) {
        return 0;
    }
    quality->changed = 1;
    quality->remount_ro_failed = ro_failed;
    return 1;
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
    char backup[C300X_MAX_PATH_LEN], cut_backup[C300X_MAX_PATH_LEN];
    struct c300x_camera_quality quality;
    struct c300x_camera_values original;
    int settings_saved, cut_saved;

    *error = "";
    if (!c300x_device_file_backup_path("bt_answering_machine", backup, sizeof(backup))
        || !c300x_device_file_backup_path(C300X_CAMERA_CROP_BACKUP, cut_backup, sizeof(cut_backup))) {
        return 1;
    }
    settings_saved = access(backup, F_OK) == 0;
    cut_saved = !low_stream() && access(cut_backup, F_OK) == 0;
    /* Never changed on this device; or files that lost the values meanwhile
     * are left alone. */
    if ((!settings_saved && !cut_saved) || !c300x_camera_quality_read(&quality)) {
        return 1;
    }
    *error = "backup_unreadable";
    if (!read_values(settings_saved ? backup : settings_path(), cut_saved ? cut_backup : crop_path(), &original)) {
        return 0;
    }
    /* After a firmware update the files hold the factory values again. */
    if (memcmp(&quality.saved, &original, sizeof(original)) == 0) {
        return 1;
    }
    return write_values(&quality, &original, error);
}
