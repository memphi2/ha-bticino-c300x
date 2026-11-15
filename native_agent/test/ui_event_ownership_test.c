/* A saved poll result must not act on a waiter that replaced its owner. */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
#include "../src/http_util.h"
#include "../src/ui_events.h"

static void respond(int fd, int status, const char *reason, const char *body, void *context)
{
    (void)context;
    c300x_http_send_json(fd, status, reason, body);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    int notify = strcmp(argv[1], "notify") == 0;
    struct c300x_ui_events events;
    struct pollfd fds[C300X_UI_EVENT_MAX_WAITERS];
    int slots[C300X_UI_EVENT_MAX_WAITERS];
    int old[C300X_UI_EVENT_MAX_WAITERS][2], replacement[2], overflowed;
    c300x_ui_events_init(&events);
    for (int i = 0; i < C300X_UI_EVENT_MAX_WAITERS; i++) {
        assert(socketpair(AF_UNIX, SOCK_STREAM, 0, old[i]) == 0);
        c300x_ui_events_store_waiter(&events, old[i][0], 0, respond, NULL, &overflowed);
        assert(!overflowed);
    }
    /* This HTTP connection already exists when the main loop polls. */
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, replacement) == 0);
    int count = c300x_ui_events_pollfds(&events, fds, slots, C300X_UI_EVENT_MAX_WAITERS);
    assert(count == C300X_UI_EVENT_MAX_WAITERS);
    close(old[0][1]);
    assert(poll(fds, count, 100) > 0);
    assert(fds[0].revents & C300X_SOCKET_CLOSED_REVENTS);

    /* HTTP request handling precedes UI waiter poll-result processing. It
     * can notify old waiters or replace the oldest one when all slots are full. */
    if (notify) c300x_ui_events_notify(&events, "ringer.muted", respond, NULL);
    c300x_ui_events_store_waiter(&events, replacement[0], events.revision, respond, NULL, &overflowed);
    assert(overflowed == !notify);
    assert(events.waiters[0].fd == replacement[0]);
    c300x_ui_events_handle_pollfds(&events, fds, slots, count, respond, NULL);
    assert(events.waiters[0].fd == replacement[0]);
    assert(c300x_ui_events_waiter_count(&events) == (notify ? 1 : C300X_UI_EVENT_MAX_WAITERS));
    char byte;
    assert(recv(replacement[1], &byte, 1, MSG_DONTWAIT) == -1);
    assert(errno == EAGAIN || errno == EWOULDBLOCK);

    /* A fresh disconnect result still closes the actual owner. */
    count = c300x_ui_events_pollfds(&events, fds, slots, C300X_UI_EVENT_MAX_WAITERS);
    close(replacement[1]);
    assert(poll(fds, count, 100) > 0);
    c300x_ui_events_handle_pollfds(&events, fds, slots, count, respond, NULL);
    assert(events.waiters[0].fd == -1);
    assert(fcntl(replacement[0], F_GETFD) == -1 && errno == EBADF);
    c300x_ui_events_close_all(&events, respond, NULL);
    for (int i = 1; i < C300X_UI_EVENT_MAX_WAITERS; i++) close(old[i][1]);
    c300x_http_outputs_close();
    return 0;
}
