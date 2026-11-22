#ifndef C100X_GUI_PRESENCE_H
#define C100X_GUI_PRESENCE_H

#include "http_request.h"
#include <poll.h>
#define C100X_GUI_PRESENCE_POLL_FDS 1

/* A live GUI lease is runtime evidence only, never installation approval. */
struct c100x_gui_presence {
    int fd;
    int blocked;
    char generation[65];
    char probe[33];
    int proved;
    long long probe_deadline_ms;
    long long deadline_ms;
};

void c100x_gui_presence_init(struct c100x_gui_presence *state);
void c100x_gui_presence_close(struct c100x_gui_presence *state);
int c100x_gui_presence_prepare(struct c100x_gui_presence *state, struct pollfd *fd);
void c100x_gui_presence_tick(struct c100x_gui_presence *state, const struct pollfd *fd);
int c100x_gui_presence_route(struct c100x_gui_presence *state, int fd,
    const struct request *request, int loopback);

#endif
