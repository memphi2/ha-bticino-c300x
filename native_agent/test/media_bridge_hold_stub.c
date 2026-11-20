/* Stands in for the media bridge in whole-agent tests: every operation is
 * written to media.log, and the session stop waits while a file "hold"
 * exists in the working directory. */
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include "../src/media_bridge.h"

static void note(const char *text)
{
    int fd = open("media.log", O_WRONLY | O_CREAT | O_APPEND, 0600);

    if (fd >= 0) {
        if (write(fd, text, strlen(text)) < 0) {
        }
        close(fd);
    }
}

bool c300x_media_bridge_start(const struct c300x_config *config, struct c300x_video *video)
{
    (void)config;
    (void)video;
    return true;
}

void c300x_media_bridge_stop(struct c300x_video *video)
{
    (void)video;
    note("bridge_stop\n");
}

bool c300x_media_ring_receiver_start(const struct c300x_config *config, struct c300x_video *video)
{
    (void)config;
    (void)video;
    return true;
}

void c300x_media_ring_receiver_stop(struct c300x_video *video)
{
    (void)video;
}

bool c300x_media_home_call_start(const struct c300x_config *config, struct c300x_video *video, int duration_seconds)
{
    char line[48];

    (void)config;
    (void)video;
    snprintf(line, sizeof(line), "home_start %d\n", duration_seconds);
    note(line);
    return true;
}

void c300x_media_home_call_stop(struct c300x_video *video)
{
    (void)video;
    note("home_stop\n");
}

void c300x_media_session_stop(struct c300x_video *video)
{
    (void)video;
    note("stop begin\n");
    while (access("hold", F_OK) == 0) {
        usleep(20000);
    }
    note("stop end\n");
}

void c300x_media_session_stop_after_rtsp_disconnect(struct c300x_video *video)
{
    (void)video;
}

void c300x_media_session_note_explicit_activate(struct c300x_video *video)
{
    (void)video;
    note("activate\n");
}

bool c300x_media_session_stop_in_progress(const struct c300x_video *video)
{
    (void)video;
    return false;
}

bool c300x_media_session_keepalive(struct c300x_video *video, bool audio)
{
    (void)video;
    (void)audio;
    return false;
}

bool c300x_media_session_resume_parked_rtsp(struct c300x_video *video, bool audio)
{
    (void)video;
    (void)audio;
    return false;
}

bool c300x_media_ring_call_answer(struct c300x_video *video)
{
    (void)video;
    note("answer\n");
    return false;
}

void c300x_media_ring_call_hangup(struct c300x_video *video)
{
    c300x_media_session_stop(video);
}

void c300x_media_bridge_set_doorstation_audio_gain_tenths(struct c300x_video *video, int gain_tenths)
{
    (void)video;
    (void)gain_tenths;
}

bool c300x_media_talkback_running(const struct c300x_video *video)
{
    (void)video;
    return false;
}

bool c300x_media_ring_call_active(const struct c300x_video *video)
{
    (void)video;
    return false;
}

void c300x_media_bridge_status(const struct c300x_video *video, struct c300x_video_status *status)
{
    (void)video;
    (void)status;
}
