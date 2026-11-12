#ifndef C300X_HTTP_RESPONSE_H
#define C300X_HTTP_RESPONSE_H

void send_response(int client_fd, int status, const char *reason, const char *body, const char *extra_headers);

#endif
