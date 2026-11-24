#ifndef C300X_PICTURE_CONTROL_H
#define C300X_PICTURE_CONTROL_H

#include "http_request.h"

struct c300x_ringer_control;
struct c300x_video_control;
struct c300x_video;
struct c300x_config;
enum picture_field { PICTURE_NONE, PICTURE_READ, PICTURE_BRIGHTNESS, PICTURE_CONTRAST, PICTURE_SATURATION };
struct picture_command { enum picture_field field; int value; };
const char *picture_name(enum picture_field field);
void picture_request(struct c300x_ringer_control *control, struct c300x_video_control *worker,
    struct c300x_video *video, const struct c300x_config *config, int fd, const struct request *request);
void picture_reply(int fd, const struct picture_command *command, const char *query);

#endif
