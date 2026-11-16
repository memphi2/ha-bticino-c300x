#ifndef C300X_HTTP_AUDIO_CODEC_H
#define C300X_HTTP_AUDIO_CODEC_H

#include "http_service_commands.h"

int c300x_http_audio_codec_route(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, const char *running_state,
    const struct request *request, c300x_schedule_command_fn schedule);

#endif
