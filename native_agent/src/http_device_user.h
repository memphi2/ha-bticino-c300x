#ifndef C300X_HTTP_DEVICE_USER_H
#define C300X_HTTP_DEVICE_USER_H

#include "http_maintenance.h"

/* API admission is the caller's responsibility; writes additionally require
 * maintenance authorization and their existing explicit confirmation. */
int c300x_http_device_user_route(struct c300x_http_maintenance *owner, int client_fd,
    const struct c300x_config *config, const struct request *request);

#endif
