#include "picture_worker.h"
#include "picture_source.h"
#include "device_detect.h"
#include "firmware_version.h"
#include "time_util.h"
#include <string.h>

enum { OWNER_NONE, OWNER_RING, OWNER_AGENT };

static int owner(const struct c300x_video_status *s)
{
    if (!s->bridge_running || !s->bridge_media_active || s->bridge_stop_in_progress
        || s->external_media_active || s->home_call_active || s->home_call_running
        || s->ring_hangup_requested) return OWNER_NONE;
    if (s->ring_call_active || s->ring_media_active)
        return s->ring_call_active && s->ring_media_active ? OWNER_RING : OWNER_NONE;
    return !strcmp(s->media_owner, "agent") ? OWNER_AGENT : OWNER_NONE;
}

static int active(void *context)
{
    const struct c300x_video_control_job *job = context;
    struct c300x_video_status status;
    if ((job->shutdown && *job->shutdown) || c300x_monotonic_ms() >= job->picture_deadline) return 0;
    c300x_video_status(job->video, &status);
    return status.picture_session == job->picture_session && owner(&status) == job->picture_owner;
}

void picture_worker_execute(struct c300x_video_control_job *job)
{
    job->result = PICTURE_SOURCE_UNAVAILABLE;
    if (!active(job)) return;
    if (!job->picture_profile) {
        char firmware[C300X_MAX_VERSION_LEN];
        /* Neither a configured display version nor the configured model (the
         * installer writes C300X on every station) proves the capture ABI. */
        resolve_device_firmware(NULL, firmware, sizeof(firmware));
        int profile = picture_source_supported(c300x_device_model_name(c300x_device_model()), firmware);
        job->picture_profile = profile ? profile : -1;
    }
    if (job->picture_profile > 0)
        job->result = picture_source_execute(job->picture_profile, &job->picture, job->values, active, job);
}

enum picture_route picture_worker_request(struct c300x_video_control *c,
    struct c300x_video *video, const struct c300x_video_status *s,
    const struct c300x_config *config, const struct picture_command *command, int values[3])
{
    struct c300x_request_worker *w = &c->worker;
    int current = owner(s);
    /* Replay belongs to the original request even when its media has ended.
     * Never dispatch its write again (including through the GUI). */
    if (w->armed_fd >= 0 && w->owner_fd == w->armed_fd && c->job.op == C300X_VIDEO_CONTROL_PICTURE) {
        if (w->running) {
            w->deferred = 1;
            return PICTURE_DEFERRED;
        }
        if (!c->has_result || !current || current != c->job.picture_owner
            || s->picture_session != c->job.picture_session) return PICTURE_UNAVAILABLE;
        int ok = c->job.result == PICTURE_SOURCE_OK;
        c->baseline_owner = current;
        c->baseline_session = s->picture_session;
        /* A failed write is never replayed; the next status must verify anew.
         * A verified baseline keeps the profile, which the next job reuses. */
        c->picture_baseline = ok ? c->job.picture_profile :
            (c->job.picture_profile < 0 || c->job.picture.field == PICTURE_READ ? -1 : 0);
        if (c->job.picture_profile < 0)
            return current == OWNER_RING ? PICTURE_LEGACY : PICTURE_UNAVAILABLE;
        if (ok) {
            if (values) memcpy(values, c->job.values, sizeof(c->job.values));
            return PICTURE_DIRECT;
        }
        if (command && command->field != PICTURE_READ)
            return c->job.result == PICTURE_SOURCE_NOT_APPLIED ? PICTURE_NOT_APPLIED : PICTURE_UNAVAILABLE;
        return current == OWNER_RING ? PICTURE_LEGACY : PICTURE_UNAVAILABLE;
    }
    if (!current) {
        if (s->home_call_running || s->home_call_active || s->external_media_active
            || s->bridge_stop_in_progress || s->ring_hangup_requested || !strcmp(s->media_owner, "agent"))
            return PICTURE_UNAVAILABLE;
        return PICTURE_LEGACY; /* Stock GUI checks its own active ring. */
    }
    int cached = c->baseline_session == s->picture_session && c->baseline_owner == current
        ? c->picture_baseline : 0;
    if (cached < 0)
        return current == OWNER_RING ? PICTURE_LEGACY : PICTURE_UNAVAILABLE;
    if (!command && cached > 0) return PICTURE_DIRECT;
    /* Refuse contention instead of queuing a picture write across a media transition. */
    if (w->armed_fd < 0 || w->running || w->owner_fd != C300X_REQUEST_WORKER_FREE
        || c300x_request_queue_first(w->queue, w) >= 0) return PICTURE_BUSY;
    c->has_result = 0;
    c->job = (struct c300x_video_control_job){.op = C300X_VIDEO_CONTROL_PICTURE,
        .video = video, .picture_owner = current, .picture_session = s->picture_session,
        .picture_config = config, .picture_profile = cached,
        .picture = command ? *command : (struct picture_command){PICTURE_READ, 0},
        .picture_deadline = c300x_monotonic_ms() + 2000, .shutdown = c->shutdown};
    return c300x_request_worker_start(w) ? PICTURE_DEFERRED : PICTURE_BUSY;
}
