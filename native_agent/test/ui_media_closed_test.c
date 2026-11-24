#include <assert.h>
#include "../src/http.c"

static long long now_ms = 100000;

long long __wrap_c300x_monotonic_ms(void)
{
    return now_ms;
}

static void notify_closed(struct agent_runtime *runtime)
{
    int pair[2];
    char response[1024];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    unsigned long revision = runtime->ui_events.revision;
    unsigned long long events = runtime->event_sequence;
    handle_ui_media_closed(pair[0], runtime->config, runtime);
    close(pair[0]);
    ssize_t size = recv(pair[1], response, sizeof(response) - 1, 0);
    assert(size > 0);
    response[size] = '\0';
    close(pair[1]);
    assert(strstr(response, "HTTP/1.1 200 OK") != NULL);
    assert(runtime->ui_events.revision == revision + 1);
    assert(runtime->event_sequence == events);
}

int main(void)
{
    struct c300x_config config = {0};
    struct agent_runtime *runtime = calloc(1, sizeof(*runtime));
    assert(runtime != NULL);
    runtime->config = &config;
    /* Disabled bridge: exercise real video state and HTTP code without device I/O. */
    runtime->video = c300x_video_create(&config, NULL, 0);
    assert(runtime->video != NULL);

    /* On-demand startup: the GUI's transient call end keeps the stream. */
    c300x_video_bridge_client_connected(runtime->video);
    c300x_video_bridge_media_starting(runtime->video);
    now_ms += 1500;
    notify_closed(runtime);
    c300x_video_bridge_media_started(runtime->video, 1);
    notify_closed(runtime);
    now_ms += 3500;
    notify_closed(runtime);
    assert(c300x_video_consume_media_closed_event(runtime->video));
    c300x_video_bridge_media_stopped(runtime->video);

    /* HA answers a ring: the station ends the display call (bus *8*3, then
     * GUI onCallEnded). HA keeps its call and the real end stays armed. */
    c300x_video_bridge_ring_media_started(runtime->video, 0);
    c300x_video_bridge_ring_media_started(runtime->video, 1);
    notify_closed(runtime);
    now_ms += 60000;
    notify_closed(runtime);
    c300x_video_bridge_media_stopped(runtime->video);
    assert(c300x_video_consume_media_closed_event(runtime->video));
    assert(!c300x_video_consume_media_closed_event(runtime->video));

    /* A display view ended on the display: the GUI hook alone stays silent. */
    c300x_video_bridge_client_disconnected(runtime->video);
    c300x_video_note_event(runtime->video, "doorbell.view_requested", 30);
    notify_closed(runtime);
    assert(c300x_video_consume_media_closed_event(runtime->video));

    c300x_video_destroy(runtime->video);
    c300x_recent_events_clear(&runtime->recent_events);
    free(runtime);
    return 0;
}
