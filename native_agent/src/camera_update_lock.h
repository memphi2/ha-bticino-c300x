#ifndef C300X_CAMERA_UPDATE_LOCK_H
#define C300X_CAMERA_UPDATE_LOCK_H

/* Serialize complete camera configuration/binary operations across processes.
 * Returns an owned fd, or -1 with a static error string; never waits for a lock.
 * Close the fd on every exit. Do not unlink the lock file (that splits ownership).
 * Default /tmp/c300x-camera-quality.lock; C300X_CAMERA_UPDATE_LOCK overrides it. */
int c300x_camera_update_lock_acquire(const char **error);

#endif
