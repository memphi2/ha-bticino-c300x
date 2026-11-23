#ifndef C300X_HTTP_RING_STATUS_H
#define C300X_HTTP_RING_STATUS_H

struct c300x_video;

void c300x_http_doorbell_call_get(int client_fd, int video_enabled, struct c300x_video *video);

#endif
