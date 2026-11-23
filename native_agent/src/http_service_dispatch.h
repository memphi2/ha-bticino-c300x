#ifndef C300X_HTTP_SERVICE_DISPATCH_H
#define C300X_HTTP_SERVICE_DISPATCH_H

#include "http_service_commands.h"

/* Only the loopback route may pass display=1, after authenticating the GUI
 * process. The public API route always uses maintenance-token authorization. */
int c300x_service_dispatch(int display, struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, const struct request *request,
    c300x_schedule_command_fn schedule);

#endif
