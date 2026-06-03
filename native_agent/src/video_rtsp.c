#include "video_rtsp.h"

#include "media_bridge.h"

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/time.h>

#include "pthread_compat.h"

#define C300X_EXTERNAL_MEDIA_GUARD_DEFAULT_SECONDS 90

struct c300x_video;
static void clear_external_media_active_locked(struct c300x_video *video);

struct c300x_video {
    const struct c300x_config *config;
    pthread_mutex_t mutex;
    int enabled;
    int running;
    int call_active;
    int clients;
    int media_starting;
    int stream_audio;
    int external_event_active;
    time_t external_active_until;
    char external_owner[32];
    char last_block_reason[64];
    unsigned long long bt_media_start_attempts;
    unsigned long long bt_media_stop_attempts;
    unsigned long long rtp_packets;
    char last_rtp_at[40];
    char last_media_started_at[40];
    char last_error[128];
};

static void utc_now(char *out, size_t out_len)
{
    struct timeval now;
    struct tm tm_utc;

    if (out_len == 0) {
        return;
    }
    gettimeofday(&now, NULL);
    gmtime_r(&now.tv_sec, &tm_utc);
    strftime(out, out_len, "%Y-%m-%dT%H:%M:%SZ", &tm_utc);
}

static void set_last_error(struct c300x_video *video, const char *message)
{
    pthread_mutex_lock(&video->mutex);
    snprintf(video->last_error, sizeof(video->last_error), "%s", message != NULL ? message : "error");
    pthread_mutex_unlock(&video->mutex);
}

static int external_media_active_locked(struct c300x_video *video)
{
    time_t now;

    if (!video->external_event_active) {
        return 0;
    }
    now = time(NULL);
    if (video->external_active_until > 0 && now >= video->external_active_until) {
        clear_external_media_active_locked(video);
        return 0;
    }
    return video->call_active == 0 && video->external_event_active;
}

static void set_external_media_active_locked(
    struct c300x_video *video,
    const char *owner,
    int ttl_seconds
) {
    time_t now = time(NULL);
    int bounded_ttl = ttl_seconds > 0
        ? ttl_seconds
        : C300X_EXTERNAL_MEDIA_GUARD_DEFAULT_SECONDS;

    video->external_event_active = 1;
    video->external_active_until = now + bounded_ttl;
    snprintf(
        video->external_owner,
        sizeof(video->external_owner),
        "%s",
        owner != NULL && owner[0] != '\0' ? owner : "external"
    );
}

static void clear_external_media_active_locked(struct c300x_video *video)
{
    video->external_event_active = 0;
    video->external_active_until = 0;
    video->external_owner[0] = '\0';
}

static int c300x_video_ensure_running(struct c300x_video *video)
{
    if (video == NULL || !video->enabled) {
        return 0;
    }

    pthread_mutex_lock(&video->mutex);
    if (video->running || video->media_starting) {
        pthread_mutex_unlock(&video->mutex);
        return 1;
    }
    video->media_starting = 1;
    pthread_mutex_unlock(&video->mutex);

    if (!c300x_media_bridge_start(video->config, video)) {
        pthread_mutex_lock(&video->mutex);
        video->media_starting = 0;
        pthread_mutex_unlock(&video->mutex);
        set_last_error(video, "media_bridge_start_failed");
        return 0;
    }

    pthread_mutex_lock(&video->mutex);
    video->running = 1;
    video->media_starting = 0;
    video->last_error[0] = '\0';
    pthread_mutex_unlock(&video->mutex);
    return 1;
}

struct c300x_video *c300x_video_create(
    const struct c300x_config *config,
    char *error,
    size_t error_len
)
{
    struct c300x_video *video = calloc(1, sizeof(*video));

    if (video == NULL) {
        if (error != NULL && error_len > 0) {
            snprintf(error, error_len, "video: out of memory");
        }
        return NULL;
    }
    video->config = config;
    video->enabled = config->video_enabled;
    pthread_mutex_init(&video->mutex, NULL);

    (void)error;
    (void)error_len;
    return video;
}

void c300x_video_destroy(struct c300x_video *video)
{
    if (video == NULL) {
        return;
    }
    if (video->enabled && video->running) {
        c300x_media_bridge_stop(video);
    }
    pthread_mutex_destroy(&video->mutex);
    free(video);
}

int c300x_video_activate(struct c300x_video *video, int include_audio)
{
    if (video == NULL || !video->enabled) {
        return 0;
    }
    pthread_mutex_lock(&video->mutex);
    if (external_media_active_locked(video)) {
        snprintf(video->last_error, sizeof(video->last_error), "%s", "external_session_active");
        snprintf(video->last_block_reason, sizeof(video->last_block_reason), "%s", "external_session_active");
        pthread_mutex_unlock(&video->mutex);
        return 0;
    }
    pthread_mutex_unlock(&video->mutex);
    if (!c300x_video_ensure_running(video)) {
        return 0;
    }
    if (c300x_media_session_keepalive(video, include_audio != 0)) {
        return 1;
    }
    pthread_mutex_lock(&video->mutex);
    video->stream_audio = include_audio != 0;
    video->last_error[0] = '\0';
    video->last_block_reason[0] = '\0';
    pthread_mutex_unlock(&video->mutex);
    return 1;
}

void c300x_video_stop(struct c300x_video *video)
{
    if (video == NULL) {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    int running = video->running;
    pthread_mutex_unlock(&video->mutex);
    if (!running) {
        c300x_video_bridge_media_stopped(video);
        return;
    }
    c300x_media_bridge_stop(video);
    pthread_mutex_lock(&video->mutex);
    video->running = 0;
    pthread_mutex_unlock(&video->mutex);
}

int c300x_video_pollfds(struct c300x_video *video, struct pollfd *fds, int max_fds)
{
    (void)video;
    (void)fds;
    (void)max_fds;
    return 0;
}

void c300x_video_handle_pollfds(struct c300x_video *video, struct pollfd *fds, int count)
{
    (void)video;
    (void)fds;
    (void)count;
}

int c300x_video_poll_timeout_ms(const struct c300x_video *video)
{
    (void)video;
    return -1;
}

void c300x_video_status(struct c300x_video *video, struct c300x_video_status *status)
{
    memset(status, 0, sizeof(*status));
    if (video == NULL) {
        return;
    }
    int talkback_running = c300x_media_talkback_running(video) ? 1 : 0;
    pthread_mutex_lock(&video->mutex);
    status->enabled = video->enabled;
    status->running = video->running;
    status->call_active = video->call_active;
    status->clients = video->clients;
    status->media_starting = video->media_starting;
    status->stream_audio = video->stream_audio;
    status->talkback_running = talkback_running;
    status->external_media_active = external_media_active_locked(video);
    status->external_active_until = video->external_active_until;
    snprintf(status->external_owner, sizeof(status->external_owner), "%s", video->external_owner);
    snprintf(status->last_block_reason, sizeof(status->last_block_reason), "%s", video->last_block_reason);
    status->bt_media_start_attempts = video->bt_media_start_attempts;
    status->bt_media_stop_attempts = video->bt_media_stop_attempts;
    status->rtp_packets = video->rtp_packets;
    snprintf(status->last_rtp_at, sizeof(status->last_rtp_at), "%s", video->last_rtp_at);
    snprintf(
        status->last_media_started_at,
        sizeof(status->last_media_started_at),
        "%s",
        video->last_media_started_at
    );
    snprintf(status->last_error, sizeof(status->last_error), "%s", video->last_error);
    pthread_mutex_unlock((pthread_mutex_t *)&video->mutex);
    c300x_media_bridge_status(video, status);
    if (status->bridge_media_active || status->call_active) {
        snprintf(status->media_owner, sizeof(status->media_owner), "%s", "agent");
    } else if (status->external_media_active) {
        snprintf(
            status->media_owner,
            sizeof(status->media_owner),
            "%s",
            status->external_owner[0] != '\0' ? status->external_owner : "external"
        );
    } else {
        snprintf(status->media_owner, sizeof(status->media_owner), "%s", "idle");
    }
}

void c300x_video_bridge_client_connected(struct c300x_video *video)
{
    if (video == NULL) {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    video->clients++;
    pthread_mutex_unlock(&video->mutex);
}

void c300x_video_bridge_client_disconnected(struct c300x_video *video)
{
    if (video == NULL) {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    if (video->clients > 0) {
        video->clients--;
    }
    pthread_mutex_unlock(&video->mutex);
}

void c300x_video_bridge_media_started(struct c300x_video *video, int include_audio)
{
    if (video == NULL) {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    if (!video->call_active) {
        video->bt_media_start_attempts++;
    }
    video->call_active = 1;
    video->media_starting = 0;
    video->stream_audio = include_audio != 0;
    video->last_error[0] = '\0';
    video->last_block_reason[0] = '\0';
    clear_external_media_active_locked(video);
    utc_now(video->last_media_started_at, sizeof(video->last_media_started_at));
    pthread_mutex_unlock(&video->mutex);
}

void c300x_video_bridge_media_stopped(struct c300x_video *video)
{
    if (video == NULL) {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    if (video->call_active) {
        video->bt_media_stop_attempts++;
    }
    video->call_active = 0;
    video->media_starting = 0;
    video->stream_audio = 0;
    pthread_mutex_unlock(&video->mutex);
}

void c300x_video_bridge_rtp_packet(struct c300x_video *video)
{
    if (video == NULL) {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    video->rtp_packets++;
    utc_now(video->last_rtp_at, sizeof(video->last_rtp_at));
    pthread_mutex_unlock(&video->mutex);
}

void c300x_video_bridge_set_error(struct c300x_video *video, const char *message)
{
    if (video == NULL) {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    snprintf(video->last_error, sizeof(video->last_error), "%s", message != NULL ? message : "error");
    pthread_mutex_unlock(&video->mutex);
}

void c300x_video_note_event(struct c300x_video *video, const char *event_type, int ttl_seconds)
{
    if (video == NULL || event_type == NULL) {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    if (
        strcmp(event_type, "doorbell.pressed") == 0
        || strcmp(event_type, "doorbell.view_requested") == 0
    ) {
        if (!video->call_active) {
            set_external_media_active_locked(video, "device_display", ttl_seconds);
        }
    } else if (
        strcmp(event_type, "doorbell.media.closed") == 0
        || strcmp(event_type, "media.closed") == 0
    ) {
        clear_external_media_active_locked(video);
    }
    pthread_mutex_unlock(&video->mutex);
}
