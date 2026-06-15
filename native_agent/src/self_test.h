#ifndef C300X_SELF_TEST_H
#define C300X_SELF_TEST_H

#include <stddef.h>

#include "c300x_agent.h"
#include "video_rtsp.h"

int c300x_self_test_json(
    const struct c300x_config *config,
    const struct c300x_video_status *video_status,
    int agent_init_script_present,
    int agent_init_link_ok,
    char *out,
    size_t out_len
);
void c300x_self_test_send_response(
    int client_fd,
    const struct c300x_config *config,
    struct c300x_video *video
);

#endif
