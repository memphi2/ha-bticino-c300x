#ifndef C300X_VIDEO_RTSP_H
#define C300X_VIDEO_RTSP_H

#include <poll.h>
#include <stddef.h>
#include <time.h>

#include "c300x_agent.h"

#define C300X_VIDEO_MAX_POLL_FDS 10
#define C300X_TALKBACK_RTP_PORT 40004
#define C300X_TALKBACK_RTP_PAYLOAD_TYPE 97
#define C300X_TALKBACK_CODEC "speex/8000"

struct c300x_video_status {
    int enabled;
    int running;
    int call_active;
    int clients;
    int media_starting;
    int stream_audio;
    int talkback_running;
    int bridge_running;
    int bridge_media_active;
    int bridge_stop_in_progress;
    int bridge_open_fds;
    int bridge_active_threads;
    int external_media_active;
    time_t external_active_until;
    char media_owner[32];
    char external_owner[32];
    char last_block_reason[64];
    unsigned long long bt_media_start_attempts;
    unsigned long long bt_media_stop_attempts;
    unsigned long long rtp_packets;
    char last_rtp_at[40];
    char last_media_started_at[40];
    char last_error[128];
};

struct c300x_video;

struct c300x_video *c300x_video_create(
    const struct c300x_config *config,
    char *error,
    size_t error_len
);
void c300x_video_destroy(struct c300x_video *video);
int c300x_video_activate(struct c300x_video *video, int include_audio);
void c300x_video_stop(struct c300x_video *video);
int c300x_video_pollfds(struct c300x_video *video, struct pollfd *fds, int max_fds);
void c300x_video_handle_pollfds(struct c300x_video *video, struct pollfd *fds, int count);
int c300x_video_poll_timeout_ms(const struct c300x_video *video);
void c300x_video_status(struct c300x_video *video, struct c300x_video_status *status);
void c300x_video_bridge_client_connected(struct c300x_video *video);
void c300x_video_bridge_client_disconnected(struct c300x_video *video);
void c300x_video_bridge_media_started(struct c300x_video *video, int include_audio);
void c300x_video_bridge_media_stopped(struct c300x_video *video);
void c300x_video_bridge_rtp_packet(struct c300x_video *video);
void c300x_video_bridge_set_error(struct c300x_video *video, const char *message);
void c300x_video_note_event(struct c300x_video *video, const char *event_type, int ttl_seconds);

#endif
