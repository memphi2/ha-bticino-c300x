#include "camera_update.h"

#include "camera_files.h"
#include "device_file.h"
#include "media_geometry_patch.h"

#include <stdlib.h>
#include <string.h>

static int same_text(const char *path, const char *original)
{
    char *now = c300x_camera_file_text(path);
    int same = now != NULL && strcmp(now, original) == 0;
    free(now);
    return same;
}

static int restore_text(const char *path, const char *original)
{
    return same_text(path, original) || (c300x_device_file_write(path, original, strlen(original))
        && same_text(path, original) && c300x_device_file_sync_parents(path));
}

int c300x_camera_update(int low, const struct c300x_camera_values *before,
    const struct c300x_camera_values *after, int geometry_before, int geometry_after,
    const char *settings, const char *crop, int *ro_failed, const char **error)
{
    char *old_settings = c300x_camera_file_text(settings);
    char *old_crop = low ? NULL : c300x_camera_file_text(crop);
    int geometry_change = !low && geometry_before != geometry_after;
    int ok = 0, geometry_ro = 0;
    struct c300x_camera_values saved;

    *error = "read_failed";
    if (old_settings == NULL || (!low && old_crop == NULL)) goto done;
    if (geometry_change && !c300x_media_geometry_prepare(geometry_after, error)) goto done;
    ok = c300x_camera_files_write(low, before, after, settings, crop, ro_failed, error);
    if (ok) {
        *error = "target_state_mismatch";
        ok = c300x_camera_files_read(low, settings, crop, &saved)
            && memcmp(&saved, after, sizeof(saved)) == 0;
    }
    if (ok) {
        *error = "config_sync_failed";
        ok = c300x_device_file_sync_parents(settings) && (low || c300x_device_file_sync_parents(crop));
    }
    if (ok && geometry_change) {
        ok = c300x_media_geometry_apply(geometry_after, &geometry_ro, error);
        *ro_failed = *ro_failed || geometry_ro;
    }
    if (ok) {
        *error = "target_state_mismatch";
        ok = c300x_camera_files_read(low, settings, crop, &saved)
            && memcmp(&saved, after, sizeof(saved)) == 0
            && (!geometry_change || (int)c300x_media_geometry_state(NULL) == geometry_after);
    }
    if (!ok) {
        const char *failure = *error;
        if (same_text(settings, old_settings) && (low || same_text(crop, old_crop))
            && (!geometry_change || (int)c300x_media_geometry_state(NULL) == geometry_before)) goto done;
        /* Preserve the exact pre-request text, not a potentially older uninstall backup. */
        int restored = c300x_device_file_remount("rw");
        if (restored) {
            restored = restore_text(settings, old_settings);
            if (!low) restored = restore_text(crop, old_crop) && restored;
            if (geometry_change)
                restored = c300x_media_geometry_apply(geometry_before, &geometry_ro, error) && restored;
            *ro_failed = !c300x_device_file_remount("ro");
        }
        *error = restored ? failure : "rollback_failed";
    }
done:
    free(old_settings);
    free(old_crop);
    if (ok) *error = "";
    return ok;
}
