#ifndef C300X_MEDIA_GEOMETRY_PATCH_H
#define C300X_MEDIA_GEOMETRY_PATCH_H

#include <sys/types.h>
#include <stddef.h>

enum c300x_media_geometry_state {
    C300X_MEDIA_GEOMETRY_UNKNOWN = -1,
    C300X_MEDIA_GEOMETRY_STOCK = 0,
    C300X_MEDIA_GEOMETRY_PATCHED = 1
};

/* Reconstruct the single expected vendor process name; no discovery or globbing. */
int c300x_media_geometry_process_name(char *buf, size_t len);

/* NULL uses C300X_MEDIA_GEOMETRY_TARGET or the exact vendor media path.
 * Regular files only; symlinks in any path component are rejected. */
enum c300x_media_geometry_state c300x_media_geometry_state(const char *path);

/* Backup: explicit C300X_MEDIA_GEOMETRY_BACKUP, otherwise
 * <C300X_AUDIO_BACKUP_DIR>/home/bticino/bin/<vendor-name>, with the standard
 * /home/bticino/cfg/extra/c300x-device-file-backups/original root by default.
 * prepare verifies/creates the stock backup, never changes the target. Only
 * stock targets can create a backup; patched targets require an existing one.
 * Each allowlisted firmware variant requires its own exact stock backup.
 * 2.0.2 is offline-verified only, not hardware-tested.
 * Backup owner and mode are preserved. No original code is embedded/reconstructed.
 * apply requires a valid prepared backup and rechecks the target.
 * enable must be 0 (stock) or 1 (960x576). Errors are static strings.
 * Failure after rename can leave the requested state installed: callers MUST
 * reread state and roll back their transaction. ro_failed is always initialized.
 * Success with ro_failed=1 means replacement succeeded but root remains writable.
 * The per-binary lock is nonblocking (geometry_busy). The caller serializes the
 * encompassing configuration/binary transaction separately, including uninstall. */
int c300x_media_geometry_prepare(int enable, const char **error);
int c300x_media_geometry_apply(int enable, int *ro_failed, const char **error);

/* prepare(0) + apply(0). Stock/unknown regular or missing target with absent backup is an
 * uninstall no-op; unknown target with any backup or an invalid backup fails
 * closed. Remount test override: existing C300X_DEVICE_PATCH_NO_REMOUNT. */
int c300x_media_geometry_restore(int *ro_failed, const char **error);

/* Hash the actual executable inode, not the pathname now installed on disk.
 * Caller supplies the verified vendor media PID. Missing/unreadable -> UNKNOWN. */
enum c300x_media_geometry_state c300x_media_geometry_running_state(pid_t pid);

#endif
