#ifndef C300X_DEVICE_FILE_H
#define C300X_DEVICE_FILE_H

#include <stddef.h>
#include <sys/types.h>

/* Vendor configuration files on the read-only root file system: read them
 * whole, replace them atomically, keep one backup of the original. All
 * functions return nonzero on success. */

#define C300X_DEVICE_FILE_MAX 262144

/* mode is "rw" or "ro". C300X_AUDIO_NO_REMOUNT=1 skips it, for tests. */
int c300x_device_file_remount(const char *mode);
/* The whole file, NUL-terminated, in memory the caller frees. */
int c300x_device_file_read(const char *path, char **data, size_t *len, mode_t *mode);
/* Temp file, fsync, rename: the target is the old or the new content, never
 * a part of it. An existing target keeps its owner and mode. */
int c300x_device_file_write(const char *path, const char *data, size_t len);
int c300x_device_file_copy(const char *source, const char *dest);
int c300x_device_file_mkdir_p(const char *path);
/* Where the originals are kept, on the writable data partition
 * (C300X_AUDIO_BACKUP_DIR overrides it for tests). */
const char *c300x_device_file_backup_dir(void);
int c300x_device_file_backup_path(const char *name, char *out, size_t out_len);
/* Copies only when dest does not exist yet. */
int c300x_device_file_backup_once(const char *source, const char *dest);

#endif
