/* The GUI follows a bus mute but not a bus unmute: the agent pushes the unmute. */
#include "../src/ringer_control.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

/* Picture commands are not part of this test. */
const char *picture_name(enum picture_field field) { (void)field; return ""; }
void picture_reply(int fd, const struct picture_command *command, const char *query)
{
    (void)fd; (void)command; (void)query;
}

static int sleeping_gui(struct c300x_ringer_control *control, const char *query, int *peer)
{
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    *peer = pair[1];
    return c300x_ringer_control_next(control, pair[0], query, NULL, NULL);
}

/* What the agent sent the GUI, or "" when it sent nothing. */
static void received(int peer, char *out, size_t size)
{
    struct timeval timeout = {0, 200000};
    ssize_t count;
    assert(setsockopt(peer, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
    count = recv(peer, out, size - 1, 0);
    out[count > 0 ? count : 0] = '\0';
}

static void sync_id(const char *response, char *id)
{
    const char *start = strstr(response, "\"id\":\"");
    assert(start != NULL);
    memcpy(id, start + 6, 32);
    id[32] = '\0';
}

int main(void)
{
    struct c300x_ringer_control control;
    char response[1024], id[33], query[128];
    int peer;

    c300x_ringer_control_init(&control);
    assert(sleeping_gui(&control, "", &peer) == 0);

    /* Not on a display without the adapter. */
    c300x_ringer_control_observe(&control, 0, 0);
    received(peer, response, sizeof(response));
    assert(response[0] == '\0');

    /* The GUI's flag is unknown: an unmute on the bus is pushed once. */
    c300x_ringer_control_observe(&control, 0, 1);
    received(peer, response, sizeof(response));
    assert(strstr(response, "\"muted\":false") != NULL);
    close(peer);
    sync_id(response, id);
    c300x_ringer_control_observe(&control, 0, 1);
    assert(control.gui_fd < 0);

    /* Its ack is taken without an HTTP client, and the GUI sleeps again. */
    snprintf(query, sizeof(query), "completed=%s&muted=0", id);
    assert(sleeping_gui(&control, query, &peer) == 0);
    received(peer, response, sizeof(response));
    assert(response[0] == '\0');
    assert(control.gui_muted == 0 && control.sync_id[0] == '\0');

    /* The GUI is known unmuted: a further unmute is not pushed. */
    c300x_ringer_control_observe(&control, 0, 1);
    received(peer, response, sizeof(response));
    assert(response[0] == '\0');

    /* A mute on the bus reaches the GUI by itself; the unmute after it is pushed. */
    c300x_ringer_control_observe(&control, 1, 1);
    received(peer, response, sizeof(response));
    assert(response[0] == '\0');
    c300x_ringer_control_observe(&control, 0, 1);
    received(peer, response, sizeof(response));
    assert(strstr(response, "\"muted\":false") != NULL);
    close(peer);

    /* With the GUI away, the push waits for its next request. */
    sync_id(response, id);
    snprintf(query, sizeof(query), "completed=%s&muted=1", id);
    assert(sleeping_gui(&control, query, &peer) == 0);
    received(peer, response, sizeof(response));
    assert(response[0] == '\0' && control.gui_muted == 1);
    c300x_ringer_control_close(&control);
    close(peer);
    c300x_ringer_control_init(&control);
    c300x_ringer_control_observe(&control, 1, 1);
    c300x_ringer_control_observe(&control, 0, 1);
    assert(control.sync_wanted);
    assert(sleeping_gui(&control, "", &peer) == 0);
    received(peer, response, sizeof(response));
    assert(strstr(response, "\"muted\":false") != NULL);
    close(peer);

    /* A stale or foreign ack still fails. */
    assert(sleeping_gui(&control, "completed=ffffffffffffffffffffffffffffffff&muted=0", &peer) == 1);
    received(peer, response, sizeof(response));
    assert(strstr(response, "ringer_gui_stale_ack") != NULL);
    close(peer);
    c300x_ringer_control_close(&control);
    return 0;
}
