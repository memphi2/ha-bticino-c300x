#include "camera_quality.h"

#include "c300x_agent.h"
#include "camera_settings.h"
#include "device_file.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* What the device started with; zero while not known. */
static int running_bitrate, running_fps;

static const char *env_or(const char *name, const char *fallback)
{
    const char *value = getenv(name);
    return (value != NULL && value[0] != '\0') ? value : fallback;
}

static const char *settings_path(void)
{
    return env_or("C300X_CAMERA_QUALITY_FILE", "/home/bticino/cfg/bt_answering_machine");
}

static int read_values(const char *path, int *bitrate, int *fps)
{
    char *data = NULL;
    size_t len = 0;
    int ok;

    if (!c300x_device_file_read(path, &data, &len, NULL)) {
        return 0;
    }
    ok = strlen(data) == len && c300x_camera_settings_parse(data, bitrate, fps);
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
    int bitrate = 0, fps = 0;

    if (fp != NULL) {
        if (fscanf(fp, "%63s", boot) != 1) {
            boot[0] = '\0';
        }
        fclose(fp);
    }
    if (boot[0] != '\0' && (fp = fopen(note, "r")) != NULL) {
        int matched = fscanf(fp, "%63s %d %d", noted, &bitrate, &fps) == 3 && strcmp(noted, boot) == 0;
        fclose(fp);
        if (matched && bitrate > 0 && fps > 0) {
            running_bitrate = bitrate;
            running_fps = fps;
            return;
        }
    }
    if (!read_values(settings_path(), &bitrate, &fps)) {
        return;
    }
    running_bitrate = bitrate;
    running_fps = fps;
    /* A note cut short must not pass for the values the device runs. */
    if (boot[0] != '\0' && snprintf(temp, sizeof(temp), "%s.tmp", note) < (int)sizeof(temp)
        && (fp = fopen(temp, "w")) != NULL) {
        int ok = fprintf(fp, "%s %d %d\n", boot, bitrate, fps) > 0;
        ok = fclose(fp) == 0 && ok;
        if (!ok || rename(temp, note) != 0) {
            unlink(temp);
        }
    }
}

int c300x_camera_quality_read(struct c300x_camera_quality *quality)
{
    memset(quality, 0, sizeof(*quality));
    quality->running_bitrate_kbps = running_bitrate;
    quality->running_fps = running_fps;
    if (!read_values(settings_path(), &quality->bitrate_kbps, &quality->fps)) {
        return 0;
    }
    quality->supported = 1;
    quality->restart_required = running_bitrate > 0
        && (quality->bitrate_kbps != running_bitrate || quality->fps != running_fps);
    return 1;
}

/* Writes both values, keeping everything else of the file. */
static int write_values(struct c300x_camera_quality *quality, int bitrate_kbps, int fps,
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
    if ((data = c300x_camera_settings_with(data, bitrate_kbps, fps)) == NULL) {
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
    if (!c300x_camera_quality_read(quality) || quality->bitrate_kbps != bitrate_kbps || quality->fps != fps) {
        return 0;
    }
    quality->changed = ok;
    quality->remount_ro_failed = ro_failed;
    return ok;
}

int c300x_camera_quality_apply(struct c300x_camera_quality *quality, int bitrate_kbps, int fps,
    const char **error)
{
    *error = "unsupported";
    if (!c300x_camera_quality_read(quality)) {
        return 0;
    }
    /* Only a value that changes is checked: one the file already has may
     * stay, even outside the offered range. */
    *error = "out_of_range";
    if ((bitrate_kbps != quality->bitrate_kbps
            && (bitrate_kbps < C300X_CAMERA_BITRATE_MIN || bitrate_kbps > C300X_CAMERA_BITRATE_MAX))
        || (fps != quality->fps && (fps < C300X_CAMERA_FPS_MIN || fps > C300X_CAMERA_FPS_MAX))) {
        return 0;
    }
    if (bitrate_kbps == quality->bitrate_kbps && fps == quality->fps) {
        return 1;
    }
    return write_values(quality, bitrate_kbps, fps, error);
}

int c300x_camera_quality_remove_patches(const char **error)
{
    char backup[C300X_MAX_PATH_LEN];
    struct c300x_camera_quality quality;
    int bitrate = 0, fps = 0;

    *error = "";
    if (!c300x_device_file_backup_path("bt_answering_machine", backup, sizeof(backup))
        || access(backup, F_OK) != 0) {
        return 1; /* never changed on this device */
    }
    *error = "backup_unreadable";
    if (!read_values(backup, &bitrate, &fps)) {
        return 0;
    }
    /* A file the device replaced meanwhile (a firmware update) is not ours to change. */
    if (!c300x_camera_quality_read(&quality)
        || (quality.bitrate_kbps == bitrate && quality.fps == fps)) {
        return 1;
    }
    return write_values(&quality, bitrate, fps, error);
}

void c300x_camera_quality_body(const struct c300x_camera_quality *quality, int rebooting,
    char *body, size_t body_len)
{
    snprintf(body, body_len,
        "{\"ok\":true,\"supported\":%s,\"bitrate_kbps\":%d,\"fps\":%d,"
        "\"running_bitrate_kbps\":%d,\"running_fps\":%d,"
        "\"bitrate_min\":%d,\"bitrate_max\":%d,\"fps_min\":%d,\"fps_max\":%d,"
        "\"restart_required\":%s,\"changed\":%s,\"remount_ro_failed\":%s,\"rebooting\":%s}\n",
        quality->supported ? "true" : "false", quality->bitrate_kbps, quality->fps,
        quality->running_bitrate_kbps, quality->running_fps,
        C300X_CAMERA_BITRATE_MIN, C300X_CAMERA_BITRATE_MAX, C300X_CAMERA_FPS_MIN, C300X_CAMERA_FPS_MAX,
        quality->restart_required ? "true" : "false", quality->changed ? "true" : "false",
        quality->remount_ro_failed ? "true" : "false", rebooting ? "true" : "false");
}
