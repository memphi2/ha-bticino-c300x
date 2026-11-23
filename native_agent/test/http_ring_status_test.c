#include "../src/http_ring_status.h"
#include "../src/http_util.h"
#include "../src/media_bridge.h"
#include "../src/openwebnet_call.h"
#include "../src/video_rtsp.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct c300x_video { int marker; };
static struct c300x_video video;
static struct c300x_video_status snapshot;
static int reads, probes, responses, ready, deferred;

int c300x_openwebnet_deferred(void)
{
    return deferred;
}

void c300x_video_status(struct c300x_video *subject, struct c300x_video_status *status)
{
    assert(subject == &video);
    reads++;
    *status = snapshot;
}

bool c300x_media_ring_talkback_peer_ready(const struct c300x_video *subject, int client_fd)
{
    assert(subject == &video && client_fd == 37 && reads == 1);
    probes++;
    return ready != 0;
}

void c300x_http_send_json(int client_fd, int status, const char *reason, const char *body)
{
    assert(client_fd == 37 && status == 200 && strcmp(reason, "OK") == 0);
    assert(strlen(body) < 2048 && body[strlen(body) - 1] == '\n');
    responses++;
    fputs(body, stdout);
}

int main(int argc, char **argv)
{
    assert(argc == 5);
    int mode = atoi(argv[1]), enabled = atoi(argv[2]);
    ready = atoi(argv[3]);
    deferred = atoi(argv[4]);
    strcpy(snapshot.media_owner, "idle");
    if (mode >= 2) {
        snapshot.ring_receiver_running = 1;
        snapshot.ring_registered = 1;
        snapshot.ring_call_active = 1;
        snapshot.ring_media_active = 1;
        snapshot.ring_audio_active = 1;
        snapshot.ring_answer_requested = 1;
        snapshot.ring_answered = mode >= 3;
        snapshot.ring_hangup_requested = mode >= 3;
        snapshot.bridge_open_fds = 17;
        snapshot.bridge_active_threads = 3;
        strcpy(snapshot.media_owner, "ring");
    }
    if (mode == 4) {
        memset(snapshot.last_error, '\001', sizeof(snapshot.last_error) - 1);
        memset(snapshot.media_owner, '\002', sizeof(snapshot.media_owner) - 1);
    }
    c300x_http_doorbell_call_get(37, enabled, mode ? &video : NULL);
    assert(reads == (mode != 0) && probes == (mode != 0) && responses == !deferred);
    return 0;
}
