#ifndef C300X_ROOT_MOUNT_H
#define C300X_ROOT_MOUNT_H

/* Every rw/ro remount of / for a device write goes through here, so writers
 * leave / as they found it. "rw" opens a write window: on a root that is
 * already writable (a shell, a remount refused while a replaced binary is
 * open) it changes nothing, and the matching "ro" leaves it writable and
 * succeeds: / is as it was found. Windows nest, also across threads; the
 * last "ro" closes them. Each successful "rw" needs exactly one "ro".
 * Returns 0 only when a remount failed, so a failed "ro" always means a
 * root this agent made writable stays writable. */
int c300x_root_remount(const char *mode);

#endif
