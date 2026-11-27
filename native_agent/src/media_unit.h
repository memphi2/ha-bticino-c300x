#ifndef C300X_MEDIA_UNIT_H
#define C300X_MEDIA_UNIT_H

#include <stddef.h>

#define C300X_MEDIA_DEVADDR_LEN 24

/* The outdoor unit an on-demand view shows: the station's
 * bt_answering_machine reads the INVITE's a=DEVADDR and sends
 * *8*4#1<own>*<DEVADDR>## for it. The request stays until the next one; a
 * session takes it when it starts and keeps it until it stops. */

/* Pure: a DEVADDR the station sends a view for: a unit address 2N or
 * 2N#M whose number before '#' is below 96. */
int c300x_media_devaddr_valid(const char *devaddr);
/* The unit of the next session, copied to out: devaddr, else fallback (the
 * configured default unit's), else 20. */
void c300x_media_unit_request(const char *devaddr, const char *fallback, char *out, size_t out_len);
/* A session starts: it shows the requested unit, else fallback's (else 20). */
void c300x_media_unit_begin(const char *fallback, char *out, size_t out_len);
void c300x_media_unit_end(void);
/* A session runs or starts for another unit than devaddr. */
int c300x_media_unit_other(const char *devaddr);

#endif
