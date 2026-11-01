#ifndef C300X_MEDIA_SIP_IO_H
#define C300X_MEDIA_SIP_IO_H

#include <stddef.h>

/* One reader per socket. Returns a complete message length, 0 on idle timeout
 * (including keepalives), or -1 on EOF/error/incomplete or invalid framing.
 * Close the connection after -1; partially consumed frames cannot be resumed.
 * timeout_ms is a positive deadline for the entire read, not each fragment. */
int c300x_media_sip_read_message(int fd, char *buffer, size_t capacity, int timeout_ms);

/* Event/media loops must resume after a standalone keepalive rather than wait
 * for another SIP message. Same contract, but also returns 0 after keepalives. */
int c300x_media_sip_poll_message(int fd, char *buffer, size_t capacity, int timeout_ms);

#endif
