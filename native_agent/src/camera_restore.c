#include "camera_quality.h"

#include "c300x_agent.h"
#include "camera_files.h"
#include "camera_update.h"
#include "camera_update_lock.h"
#include "device_file.h"
#include "media_geometry_patch.h"

#include <string.h>
#include <unistd.h>

static int camera_quality_remove_patches_locked(const char **error)
{
    char backup[C300X_MAX_PATH_LEN], cut_backup[C300X_MAX_PATH_LEN];
    struct c300x_camera_values current, original;
    const char *settings = c300x_camera_settings_path(), *crop = c300x_camera_crop_path();
    int low = c300x_device_display_is_qt5(), ro_failed = 0;
    int geometry = c300x_media_geometry_state(NULL);

    *error = "backup_path_invalid";
    if (!c300x_device_file_backup_path("bt_answering_machine", backup, sizeof(backup))
        || !c300x_device_file_backup_path(C300X_CAMERA_CROP_BACKUP, cut_backup, sizeof(cut_backup))) return 0;
    int settings_saved = access(backup, F_OK) == 0;
    int cut_saved = !low && access(cut_backup, F_OK) == 0;
    /* Unknown executables must never be changed using a backup from another firmware. */
    if (geometry == C300X_MEDIA_GEOMETRY_UNKNOWN
        && !c300x_media_geometry_restore(&ro_failed, error)) return 0;
    if (!settings_saved && !cut_saved)
        return c300x_media_geometry_restore(&ro_failed, error);
    if (!c300x_camera_files_read(low, settings, crop, &current)) {
        if (geometry != C300X_MEDIA_GEOMETRY_UNKNOWN) {
            *error = "managed_camera_config_unreadable";
            return 0;
        }
        return c300x_media_geometry_restore(&ro_failed, error);
    }
    *error = "backup_unreadable";
    if (!c300x_camera_files_read(low, settings_saved ? backup : settings,
            cut_saved ? cut_backup : crop, &original)) return 0;
    int patched = geometry == C300X_MEDIA_GEOMETRY_PATCHED;
    if ((memcmp(&current, &original, sizeof(original)) != 0 || patched)
        && !c300x_camera_update(low, &current, &original, patched, 0,
            settings, crop, &ro_failed, error)) return 0;
    return c300x_media_geometry_restore(&ro_failed, error);
}

int c300x_camera_quality_remove_patches(const char **error)
{
    int fd = c300x_camera_update_lock_acquire(error);
    if (fd < 0) return 0;
    int ok = camera_quality_remove_patches_locked(error);
    close(fd);
    return ok;
}
