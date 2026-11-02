#ifndef C300X_HTTP_RESPONSE_H
#define C300X_HTTP_RESPONSE_H

void send_response(int client_fd, int status, const char *reason, const char *body, const char *extra_headers);
void send_file_response(int client_fd, const char *path, const char *content_type, const char *cache_control);

#endif
