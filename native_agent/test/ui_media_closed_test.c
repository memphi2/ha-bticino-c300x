#include <assert.h>
#include "../src/http.c"

static long long now_ms = 100000;

long long __wrap_c300x_monotonic_ms(void)
{
    return now_ms;
}

static void notify_closed(struct agent_runtime *runtime, int expected_events)
{
    int pair[2];
    char response[1024];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    unsigned long revision = runtime->ui_events.revision;
    handle_ui_media_closed(pair[0], runtime->config, runtime);
    close(pair[0]);
    ssize_t size = recv(pair[1], response, sizeof(response) - 1, 0);
    assert(size > 0);
    response[size] = '\0';
    close(pair[1]);
    assert(strstr(response, "HTTP/1.1 200 OK") != NULL);
    assert(runtime->ui_events.revision == revision + 1);
    assert(runtime->event_sequence == (unsigned long long)expected_events);
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

    c300x_video_bridge_client_connected(runtime->video);
    c300x_video_bridge_media_starting(runtime->video);
    now_ms += 1500;
    notify_closed(runtime, 0);
    assert(c300x_video_ignore_transient_media_closed(runtime->video));

    c300x_video_bridge_media_started(runtime->video, 1);
    notify_closed(runtime, 0);
    now_ms += 3499;
    notify_closed(runtime, 0);
    now_ms++;
    assert(!c300x_video_ignore_transient_media_closed(runtime->video));
    c300x_video_bridge_media_stopped(runtime->video);
    notify_closed(runtime, 1);
    notify_closed(runtime, 1);

    /* An actual stop clears startup protection even inside its grace period. */
    c300x_video_bridge_media_started(runtime->video, 1);
    c300x_video_bridge_media_stopped(runtime->video);
    notify_closed(runtime, 2);
    notify_closed(runtime, 2);

    /* Ring media has no on-demand startup grace. */
    c300x_video_bridge_ring_media_started(runtime->video, 0);
    assert(!c300x_video_ignore_transient_media_closed(runtime->video));
    c300x_video_bridge_media_stopped(runtime->video);
    notify_closed(runtime, 3);

    c300x_video_bridge_client_disconnected(runtime->video);
    c300x_video_note_event(runtime->video, "doorbell.view_requested", 30);
    notify_closed(runtime, 4);
    notify_closed(runtime, 4);

    c300x_video_destroy(runtime->video);
    c300x_recent_events_clear(&runtime->recent_events);
    free(runtime);
    return 0;
}
