#ifndef C300X_HTTP_CLIENT_INPUT_H
#define C300X_HTTP_CLIENT_INPUT_H

#include "http_clients.h"

/* -1: close, 0: incomplete, 1: complete. Never waits for input. */
int c300x_http_client_receive(struct c300x_http_client *client, const struct pollfd *fd);

#endif
