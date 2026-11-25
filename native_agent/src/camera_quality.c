#include "camera_quality.h"

#include "c300x_agent.h"
#include "camera_files.h"
#include "camera_running.h"
#include "camera_update.h"
#include "camera_update_lock.h"
#include "device_detect.h"
#include "device_file.h"
#include "media_geometry_patch.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* What the device started with; zero while not known. */
static struct c300x_camera_values running;

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
    c300x_camera_running_load(low_stream(), c300x_camera_settings_path(), c300x_camera_crop_path(), &running);
}

/* Describe verified saved values. Process observation may be unknown, but does
 * not invalidate a configuration transaction that has already committed. */
static void describe_values(struct c300x_camera_quality *quality, int geometry)
{
    quality->geometry_supported = geometry != C300X_MEDIA_GEOMETRY_UNKNOWN;
    quality->geometry_enabled = geometry == C300X_MEDIA_GEOMETRY_PATCHED;
    int running_geometry;
    quality->restart_required = c300x_camera_running_read(quality->low, &running, &quality->saved,
        geometry, &quality->running, &running_geometry);
    c300x_camera_quality_size_name(quality->low, &quality->running, quality->running_size,
        sizeof(quality->running_size));
    quality->supported = 1;
    c300x_camera_quality_size_name(quality->low, &quality->saved, quality->size, sizeof(quality->size));
    if (quality->geometry_enabled)
        snprintf(quality->size, sizeof(quality->size), "960x%d", quality->saved.crop[3]);
    if (!quality->low && quality->running.bitrate_kbps > 0 && running_geometry == C300X_MEDIA_GEOMETRY_PATCHED)
        snprintf(quality->running_size, sizeof(quality->running_size), "960x%d", quality->running.crop[3]);
    else if (quality->geometry_supported && running_geometry == C300X_MEDIA_GEOMETRY_UNKNOWN)
        quality->running_size[0] = '\0';
}

int c300x_camera_quality_read(struct c300x_camera_quality *quality)
{
    memset(quality, 0, sizeof(*quality));
    quality->low = low_stream();
    int geometry = quality->low ? C300X_MEDIA_GEOMETRY_UNKNOWN : c300x_media_geometry_state(NULL);
    if (!read_values(c300x_camera_settings_path(), c300x_camera_crop_path(), &quality->saved)) {
        return 0;
    }
    describe_values(quality, geometry);
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
    int geometry, const char **error)
{
    struct c300x_camera_values now = quality->saved;
    int ro_failed = 0;

    if (!c300x_camera_update(quality->low, &now, values, quality->geometry_enabled, geometry,
            c300x_camera_settings_path(), c300x_camera_crop_path(), &ro_failed, error)) {
        return 0;
    }
    quality->saved = *values;
    describe_values(quality, quality->geometry_supported ? geometry : C300X_MEDIA_GEOMETRY_UNKNOWN);
    quality->changed = 1;
    quality->remount_ro_failed = ro_failed;
    return 1;
}

static int in_range(int value, int saved, int minimum, int maximum)
{
    /* A value the file already has may stay, even outside the range. */
    return value == saved || (value >= minimum && value <= maximum);
}

static int camera_quality_apply_locked(struct c300x_camera_quality *quality, int bitrate_kbps, int fps,
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
    int geometry = size == NULL ? quality->geometry_enabled : strcmp(size, "960x576") == 0;
    /* The size the file gives already stays as it is written there. */
    *error = "invalid_size";
    if (geometry && (!quality->geometry_supported || quality->low)) return 0;
    if (size != NULL && strcmp(size, quality->size) != 0
        && !c300x_camera_quality_size_values(quality->low, size, &target)) {
        return 0;
    }
    /* Both encoder caps must use the full-height crop with the 960-wide patch. */
    if (geometry && !c300x_camera_quality_size_values(0, "960x576", &target)) return 0;
    *error = "out_of_range";
    if (!in_range(bitrate_kbps, quality->saved.bitrate_kbps, limits->bitrate_min, limits->bitrate_max)
        || !in_range(fps, quality->saved.fps, limits->fps_min, limits->fps_max)) {
        return 0;
    }
    if (memcmp(&target, &quality->saved, sizeof(target)) == 0 && geometry == quality->geometry_enabled) {
        return 1;
    }
    /* Unreadable when the agent started: before its first change the file
     * holds what the device read, as the agent assumes at its start. */
    if (running.bitrate_kbps <= 0) {
        c300x_camera_quality_note_running();
    }
    if (!c300x_camera_running_prepare(&running, error)) return 0;
    return write_values(quality, &target, geometry, error);
}

int c300x_camera_quality_apply(struct c300x_camera_quality *quality, int bitrate_kbps, int fps,
    const char *size, const char **error)
{
    int fd = c300x_camera_update_lock_acquire(error);
    if (fd < 0) return 0;
    int ok = camera_quality_apply_locked(quality, bitrate_kbps, fps, size, error);
    close(fd);
    return ok;
}
