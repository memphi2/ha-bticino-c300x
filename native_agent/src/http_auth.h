#ifndef C300X_HTTP_AUTH_H
#define C300X_HTTP_AUTH_H

#include "c300x_agent.h"
#include "http_request.h"

/* Shared policy; API admission and route-specific maintenance gates are distinct. */
int header_value(const struct request *request, const char *name, char *out, size_t out_len);
int api_request_authorized(const struct c300x_config *config, const struct request *request);
int maintenance_authorized(const struct c300x_config *config, const struct request *request);
int maintenance_auth_available(const struct c300x_config *config);
int config_admin_authorized(const struct c300x_config *config, const struct request *request);
int auth_config_read_authorized(const struct c300x_config *config, const struct request *request);
int confirm_matches(const struct request *request, const char *expected);

#endif
