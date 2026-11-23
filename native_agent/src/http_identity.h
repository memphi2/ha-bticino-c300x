#ifndef C300X_HTTP_IDENTITY_H
#define C300X_HTTP_IDENTITY_H

#include "c300x_agent.h"
#include "http_request.h"

/* 1 when the request was the identity proof route and has been answered. */
int c300x_http_identity_route(
    int client_fd,
    const struct c300x_config *config,
    const struct request *request
);

#endif
