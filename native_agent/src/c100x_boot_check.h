#ifndef C100X_BOOT_CHECK_H
#define C100X_BOOT_CHECK_H

/* The reason the service start recorded for a failed boot check of a pending
 * display trial ("payload_unavailable" or "boot_check_failed"), else "". */
const char *c100x_boot_check(void);

#endif
