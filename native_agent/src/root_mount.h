#ifndef C300X_ROOT_MOUNT_H
#define C300X_ROOT_MOUNT_H

/* Every rw/ro remount of / for a device write goes through here, so writers
 * leave / as they found it. "rw" opens a write window: on a root that is
 * already writable (a shell, a remount refused while a replaced binary is
 * open) it changes nothing. Windows nest, also across threads; the last
 * "ro" closes it, and answers 0 when / was found writable and stays so.
 * Each successful "rw" needs exactly one "ro". Returns 1 when / has the
 * requested mode (or will get it from the outer window). */
int c300x_root_remount(const char *mode);

#endif
