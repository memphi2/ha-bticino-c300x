#ifndef C300X_HTTP_ANNOUNCE_H
#define C300X_HTTP_ANNOUNCE_H

#include "announce.h"
#include "http_request.h"

/* /api/v1/announcements: status, the sound file in pieces, play and stop.
 * Called only after API admission. */
int c300x_http_announce_route(struct c300x_announce *announce, int fd, const struct request *request);

#endif
