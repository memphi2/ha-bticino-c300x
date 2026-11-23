#ifndef C100X_HTTP_DISPLAY_H
#define C100X_HTTP_DISPLAY_H

#include "announce.h"
#include "c100x_activation.h"
#include "c100x_gui_presence.h"
#include "http_service_commands.h"

struct c300x_video;

/* Payload next to the agent's configuration; inert on a C300X. */
void c100x_display_init(struct c100x_activation *activation, const struct c300x_config *config);
/* One loop step with what the agent sees; schedules the reboot once it is due. */
void c100x_display_step(struct c100x_activation *activation, const struct c300x_config *config,
    struct c300x_video *video, const struct c300x_announce *announce,
    const struct c300x_http_maintenance *maintenance, const struct c100x_gui_presence *presence,
    c300x_schedule_command_fn schedule);

#endif
