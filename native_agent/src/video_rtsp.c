#include "video_rtsp.h"
#include "string_util.h"

#include "media_bridge.h"

#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/time.h>
#include <unistd.h>

#include "pthread_compat.h"

#define C300X_VIDEO_MAX_PENDING_EVENTS 8
#define C300X_VIDEO_EVENT_TYPE_LEN 64
#define C300X_VIDEO_EVENT_DATA_LEN 512
#define C300X_EXTERNAL_MEDIA_GUARD_DEFAULT_SECONDS 30
#define C300X_EXTERNAL_MEDIA_GUARD_MAX_SECONDS 120
#define C300X_ONDEMAND_START_MEDIA_CLOSED_GRACE_MS 3500

struct c300x_video;
static void clear_external_media_active_locked(struct c300x_video *video);

struct c300x_video_event {
    char event_type[C300X_VIDEO_EVENT_TYPE_LEN];
    char data_json[C300X_VIDEO_EVENT_DATA_LEN];
    int ttl_seconds;
};

struct c300x_video {
    const struct c300x_config *config;
    pthread_mutex_t mutex;
    int enabled;
    int running;
    int call_active;
    int clients;
    int media_starting;
    int media_closed_event_armed;
    long long media_closed_grace_until_ms;
    int stream_audio;
    int external_event_active;
    long long external_event_expires_ms;
    char external_owner[32];
    char last_block_reason[64];
    unsigned long long bt_media_start_attempts;
    unsigned long long bt_media_stop_attempts;
    unsigned long long rtp_packets;
    char last_rtp_at[40];
    char last_media_started_at[40];
    char last_error[128];
    int event_read_fd;
    int event_write_fd;
    struct c300x_video_event pending_events[C300X_VIDEO_MAX_PENDING_EVENTS];
    int pending_event_count;
    c300x_video_event_callback event_callback;
    void *event_callback_user_data;
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

static long long monotonic_ms(void)
{
    struct timeval now;

    gettimeofday(&now, NULL);
    return ((long long)now.tv_sec * 1000LL) + ((long long)now.tv_usec / 1000LL);
}

static int external_media_active_locked(struct c300x_video *video)
{
    long long now;

    if (!video->external_event_active) {
        return 0;
    }
    now = monotonic_ms();
    if (video->external_event_expires_ms > 0 && now >= video->external_event_expires_ms) {
        clear_external_media_active_locked(video);
        return 0;
    }
    return video->call_active == 0 && video->media_starting == 0 && video->external_event_active;
}

static int external_media_guard_ttl_seconds(int ttl_seconds)
{
    if (ttl_seconds <= 0) {
        return C300X_EXTERNAL_MEDIA_GUARD_DEFAULT_SECONDS;
    }
    if (ttl_seconds > C300X_EXTERNAL_MEDIA_GUARD_MAX_SECONDS) {
        return C300X_EXTERNAL_MEDIA_GUARD_MAX_SECONDS;
    }
    return ttl_seconds;
}

static void set_external_media_active_locked(
    struct c300x_video *video,
    const char *owner,
    int ttl_seconds
) {
    video->external_event_active = 1;
    video->external_event_expires_ms =
        monotonic_ms() + ((long long)external_media_guard_ttl_seconds(ttl_seconds) * 1000LL);
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
    video->external_event_expires_ms = 0;
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

static void set_fd_nonblocking(int fd)
{
    int flags;

    if (fd < 0) {
        return;
    }
    flags = fcntl(fd, F_GETFL, 0);
    if (flags >= 0) {
        (void)fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    }
    flags = fcntl(fd, F_GETFD, 0);
    if (flags >= 0) {
        (void)fcntl(fd, F_SETFD, flags | FD_CLOEXEC);
    }
}

static void close_event_pipe(struct c300x_video *video)
{
    if (video->event_read_fd >= 0) {
        close(video->event_read_fd);
        video->event_read_fd = -1;
    }
    if (video->event_write_fd >= 0) {
        close(video->event_write_fd);
        video->event_write_fd = -1;
    }
}

static void drain_event_pipe(int fd)
{
    char buffer[32];

    if (fd < 0) {
        return;
    }
    for (;;) {
        if (read(fd, buffer, sizeof(buffer)) <= 0) {
            return;
        }
    }
}

struct c300x_video *c300x_video_create(
    const struct c300x_config *config,
    char *error,
    size_t error_len
)
{
    struct c300x_video *video = calloc(1, sizeof(*video));
    int event_pipe[2] = {-1, -1};

    if (video == NULL) {
        if (error != NULL && error_len > 0) {
            c300x_copy_string(error, error_len, "video: out of memory");
        }
        return NULL;
    }
    video->config = config;
    video->enabled = config->video_enabled;
    video->event_read_fd = -1;
    video->event_write_fd = -1;
    pthread_mutex_init(&video->mutex, NULL);
    if (pipe(event_pipe) == 0) {
        set_fd_nonblocking(event_pipe[0]);
        set_fd_nonblocking(event_pipe[1]);
        video->event_read_fd = event_pipe[0];
        video->event_write_fd = event_pipe[1];
    }
    (void)c300x_video_ensure_running(video);

    (void)error;
    (void)error_len;
    return video;
}

void c300x_video_destroy(struct c300x_video *video)
{
    if (video == NULL) {
        return;
    }
    if (video->enabled) {
        c300x_media_bridge_stop(video);
    }
    c300x_media_home_call_stop(video);
    c300x_media_ring_receiver_stop(video);
    close_event_pipe(video);
    pthread_mutex_destroy(&video->mutex);
    free(video);
}

void c300x_video_set_ring_receiver_enabled(struct c300x_video *video, int enabled)
{
    if (video == NULL) {
        return;
    }
    if (enabled) {
        (void)c300x_media_ring_receiver_start(video->config, video);
    } else {
        c300x_media_ring_receiver_stop(video);
    }
}

int c300x_video_activate(struct c300x_video *video, int include_audio)
{
    if (video == NULL || !video->enabled) {
        return 0;
    }
    if (c300x_media_ring_call_active(video)) {
        return 1;
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
    c300x_media_session_stop(video);
}

int c300x_video_doorbell_call_answer(struct c300x_video *video)
{
    if (video == NULL || !video->enabled) {
        return 0;
    }
    return c300x_media_ring_call_answer(video) ? 1 : 0;
}

void c300x_video_doorbell_call_hangup(struct c300x_video *video)
{
    if (video == NULL) {
        return;
    }
    c300x_media_ring_call_hangup(video);
}

void c300x_video_set_doorstation_audio_gain_tenths(
    struct c300x_video *video,
    int gain_tenths
) {
    if (video == NULL || !video->enabled) {
        return;
    }
    c300x_media_bridge_set_doorstation_audio_gain_tenths(video, gain_tenths);
}

int c300x_video_home_call_start(struct c300x_video *video, int duration_seconds)
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
    if (!c300x_media_home_call_start(video->config, video, duration_seconds)) {
        pthread_mutex_lock(&video->mutex);
        if (video->last_error[0] == '\0') {
            snprintf(video->last_error, sizeof(video->last_error), "%s", "home_call_start_failed");
        }
        pthread_mutex_unlock(&video->mutex);
        return 0;
    }
    pthread_mutex_lock(&video->mutex);
    video->last_error[0] = '\0';
    video->last_block_reason[0] = '\0';
    pthread_mutex_unlock(&video->mutex);
    return 1;
}

void c300x_video_home_call_stop(struct c300x_video *video)
{
    if (video == NULL) {
        return;
    }
    c300x_media_home_call_stop(video);
}

int c300x_video_pollfds(struct c300x_video *video, struct pollfd *fds, int max_fds)
{
    if (video == NULL || fds == NULL || max_fds <= 0 || video->event_read_fd < 0) {
        return 0;
    }
    fds[0].fd = video->event_read_fd;
    fds[0].events = POLLIN;
    fds[0].revents = 0;
    return 1;
}

void c300x_video_handle_pollfds(struct c300x_video *video, struct pollfd *fds, int count)
{
    struct c300x_video_event event;

    if (video == NULL || fds == NULL || count <= 0 || video->event_read_fd < 0) {
        return;
    }
    if (fds[0].fd != video->event_read_fd || (fds[0].revents & POLLIN) == 0) {
        return;
    }
    drain_event_pipe(video->event_read_fd);
    for (;;) {
        c300x_video_event_callback callback;
        void *user_data;

        pthread_mutex_lock(&video->mutex);
        if (video->pending_event_count <= 0) {
            pthread_mutex_unlock(&video->mutex);
            break;
        }
        event = video->pending_events[0];
        if (video->pending_event_count > 1) {
            memmove(
                &video->pending_events[0],
                &video->pending_events[1],
                sizeof(video->pending_events[0]) * (size_t)(video->pending_event_count - 1)
            );
        }
        video->pending_event_count--;
        callback = video->event_callback;
        user_data = video->event_callback_user_data;
        pthread_mutex_unlock(&video->mutex);

        if (callback != NULL) {
            callback(user_data, event.event_type, event.data_json, event.ttl_seconds);
        }
    }
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
    status->max_clients = 1;
    status->media_starting = video->media_starting;
    status->stream_audio = video->stream_audio;
    status->talkback_running = talkback_running;
    status->external_media_active = external_media_active_locked(video);
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
    if (status->ring_call_active) {
        snprintf(status->media_owner, sizeof(status->media_owner), "%s", "ring");
    } else if (status->home_call_active || status->home_call_running) {
        snprintf(status->media_owner, sizeof(status->media_owner), "%s", "home_call");
    } else if (status->bridge_media_active || status->call_active) {
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

void c300x_video_set_event_callback(
    struct c300x_video *video,
    c300x_video_event_callback callback,
    void *user_data
) {
    if (video == NULL) {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    video->event_callback = callback;
    video->event_callback_user_data = user_data;
    pthread_mutex_unlock(&video->mutex);
}

void c300x_video_dispatch_event(
    struct c300x_video *video,
    const char *event_type,
    const char *data_json,
    int ttl_seconds
) {
    int write_fd;
    char wake = 'e';
    ssize_t written;

    if (video == NULL || event_type == NULL || event_type[0] == '\0') {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    if (video->event_write_fd < 0) {
        pthread_mutex_unlock(&video->mutex);
        return;
    }
    if (video->pending_event_count >= C300X_VIDEO_MAX_PENDING_EVENTS) {
        memmove(
            &video->pending_events[0],
            &video->pending_events[1],
            sizeof(video->pending_events[0]) * (C300X_VIDEO_MAX_PENDING_EVENTS - 1)
        );
        video->pending_event_count = C300X_VIDEO_MAX_PENDING_EVENTS - 1;
    }
    snprintf(
        video->pending_events[video->pending_event_count].event_type,
        sizeof(video->pending_events[video->pending_event_count].event_type),
        "%s",
        event_type
    );
    snprintf(
        video->pending_events[video->pending_event_count].data_json,
        sizeof(video->pending_events[video->pending_event_count].data_json),
        "%s",
        data_json != NULL ? data_json : "{}"
    );
    video->pending_events[video->pending_event_count].ttl_seconds = ttl_seconds;
    video->pending_event_count++;
    write_fd = video->event_write_fd;
    pthread_mutex_unlock(&video->mutex);

    written = write(write_fd, &wake, 1);
    if (written < 0) {
        return;
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

void c300x_video_bridge_media_starting(struct c300x_video *video)
{
    if (video == NULL) {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    video->media_starting = 1;
    video->media_closed_grace_until_ms =
        monotonic_ms() + C300X_ONDEMAND_START_MEDIA_CLOSED_GRACE_MS;
    clear_external_media_active_locked(video);
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
    video->media_closed_event_armed = 1;
    video->media_closed_grace_until_ms =
        monotonic_ms() + C300X_ONDEMAND_START_MEDIA_CLOSED_GRACE_MS;
    video->stream_audio = include_audio != 0;
    video->last_error[0] = '\0';
    video->last_block_reason[0] = '\0';
    clear_external_media_active_locked(video);
    utc_now(video->last_media_started_at, sizeof(video->last_media_started_at));
    pthread_mutex_unlock(&video->mutex);
}

void c300x_video_bridge_ring_media_started(struct c300x_video *video, int include_audio)
{
    if (video == NULL) {
        return;
    }
    pthread_mutex_lock(&video->mutex);
    video->call_active = 1;
    video->media_starting = 0;
    video->media_closed_event_armed = 1;
    video->stream_audio = include_audio != 0;
    video->last_error[0] = '\0';
    video->last_block_reason[0] = '\0';
    clear_external_media_active_locked(video);
    utc_now(video->last_media_started_at, sizeof(video->last_media_started_at));
    pthread_mutex_unlock(&video->mutex);
    if (!include_audio) {
        c300x_video_dispatch_event(video, "doorbell.pressed", "{}", 0);
    }
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
    video->media_closed_grace_until_ms = 0;
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
    int ring_call_active;

    if (video == NULL || event_type == NULL) {
        return;
    }
    ring_call_active = c300x_media_ring_call_active(video) ? 1 : 0;
    pthread_mutex_lock(&video->mutex);
    if (strcmp(event_type, "doorbell.pressed") == 0) {
        /* Ringing alone is claimable by HA; it is not an external media owner. */
    } else if (strcmp(event_type, "doorbell.view_requested") == 0) {
        if (!video->call_active && !ring_call_active) {
            set_external_media_active_locked(video, "external_media", ttl_seconds);
            video->media_closed_event_armed = 1;
        }
    } else if (
        strcmp(event_type, "doorbell.media.closed") == 0
        || strcmp(event_type, "media.closed") == 0
    ) {
        video->media_closed_event_armed = 0;
        clear_external_media_active_locked(video);
    }
    pthread_mutex_unlock(&video->mutex);
}

int c300x_video_consume_media_closed_event(struct c300x_video *video)
{
    int armed;

    if (video == NULL) {
        return 0;
    }
    pthread_mutex_lock(&video->mutex);
    armed = (
        video->media_closed_event_armed
        || video->call_active
        || video->media_starting
        || external_media_active_locked(video)
    );
    if (armed) {
        video->media_closed_event_armed = 0;
        clear_external_media_active_locked(video);
    }
    pthread_mutex_unlock(&video->mutex);
    return armed;
}

int c300x_video_ignore_transient_media_closed(struct c300x_video *video)
{
    long long now;
    int ignore;

    if (video == NULL) {
        return 0;
    }
    now = monotonic_ms();
    pthread_mutex_lock(&video->mutex);
    ignore = (
        video->clients > 0
        && (video->call_active || video->media_starting)
        && video->media_closed_grace_until_ms > 0
        && now < video->media_closed_grace_until_ms
    );
    pthread_mutex_unlock(&video->mutex);
    return ignore;
}
