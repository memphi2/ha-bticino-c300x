#ifndef C300X_ROOT_MOUNT_H
#define C300X_ROOT_MOUNT_H

/* Every rw/ro remount of / for a device write goes through here, so writers
 * leave / as they found it. "rw" opens a write window: on a root that is
 * already writable (a shell, another process) it changes nothing, and the
 * matching "ro" leaves it writable and succeeds: / is as it was found.
 * Windows nest, also across threads; the last "ro" closes them. Each
 * successful "rw" needs exactly one "ro".
 * A root this agent made writable and could not close (busy while a replaced
 * binary is open) stays its own, also across an agent restart: the next
 * window takes it as its own and its "ro" retries the close. Returns 0 only
 * when a remount failed on a root the window found read-only, so a failed
 * "ro" means a root this agent made writable stays writable. */
int c300x_root_remount(const char *mode);

/* Retries the close of a root this agent left writable, when no window is
 * open; before a check that refuses a writable root (agent update). */
void c300x_root_close_left_open(void);

#endif
