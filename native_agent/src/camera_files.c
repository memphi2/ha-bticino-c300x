#include "camera_files.h"

#include "c300x_agent.h"
#include "camera_crop.h"
#include "device_file.h"

#include <stdlib.h>
#include <string.h>

struct pending_file {
    const char *path;
    const char *backup_name;
    char *data;
};

const char *c300x_camera_settings_path(void)
{
    const char *path = getenv("C300X_CAMERA_QUALITY_FILE");
    return path != NULL && path[0] != '\0' ? path : "/home/bticino/cfg/bt_answering_machine";
}

const char *c300x_camera_crop_path(void)
{
    const char *path = getenv("C300X_CAMERA_CROP_FILE");
    return path != NULL && path[0] != '\0' ? path : "/home/bticino/cfg/stack_open.xml";
}

char *c300x_camera_file_text(const char *path)
{
    char *data = NULL;
    size_t len = 0;

    if (!c300x_device_file_read(path, &data, &len, NULL)) {
        return NULL;
    }
    if (strlen(data) != len) {
        free(data);
        return NULL;
    }
    return data;
}

int c300x_camera_files_read(int low, const char *settings_path, const char *crop_path,
    struct c300x_camera_values *values)
{
    char *data;
    int ok;

    memset(values, 0, sizeof(*values));
    if ((data = c300x_camera_file_text(settings_path)) == NULL) {
        return 0;
    }
    ok = c300x_camera_settings_parse(data, low, values);
    free(data);
    if (!ok || low) {
        return ok;
    }
    if ((data = c300x_camera_file_text(crop_path)) == NULL) {
        return 0;
    }
    ok = c300x_camera_crop_parse(data, values->crop);
    free(data);
    return ok;
}

static int backup(const struct pending_file *file)
{
    char path[C300X_MAX_PATH_LEN];

    return file->data == NULL || (c300x_device_file_backup_path(file->backup_name, path, sizeof(path))
        && c300x_device_file_backup_once(file->path, path)
        && c300x_device_file_sync_parents(path));
}

int c300x_camera_files_write(int low, const struct c300x_camera_values *now,
    const struct c300x_camera_values *target, const char *settings_path, const char *crop_path,
    int *remount_ro_failed, const char **error)
{
    struct pending_file files[2] = {
        {settings_path, "bt_answering_machine", NULL}, {crop_path, C300X_CAMERA_CROP_BACKUP, NULL},
    };
    int ok = 1;

    *error = "read_failed";
    if (now->bitrate_kbps != target->bitrate_kbps || now->fps != target->fps
        || now->width != target->width || now->height != target->height) {
        files[0].data = c300x_camera_file_text(settings_path);
        ok = (files[0].data = files[0].data != NULL
            ? c300x_camera_settings_with(files[0].data, low, target) : NULL) != NULL;
    }
    if (ok && !low && memcmp(now->crop, target->crop, sizeof(now->crop)) != 0) {
        files[1].data = c300x_camera_file_text(crop_path);
        ok = (files[1].data = files[1].data != NULL ? c300x_camera_crop_with(files[1].data, target->crop) : NULL)
            != NULL;
    }
    if (ok) {
        *error = "backup_failed";
        ok = c300x_device_file_mkdir_p(c300x_device_file_backup_dir()) && backup(&files[0]) && backup(&files[1]);
    }
    if (ok) {
        *error = "remount_rw_failed";
        ok = c300x_device_file_remount("rw");
        if (ok) {
            *error = "write_failed";
            for (int i = 0; i < 2 && ok; i++) {
                ok = files[i].data == NULL || c300x_device_file_write(files[i].path, files[i].data,
                    strlen(files[i].data));
            }
            /* A root that stays writable does not undo the write; the next
             * start mounts it read-only again. */
            *remount_ro_failed = !c300x_device_file_remount("ro");
        }
    }
    free(files[0].data);
    free(files[1].data);
    return ok;
}
