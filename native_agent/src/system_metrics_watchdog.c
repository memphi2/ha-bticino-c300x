#include "system_metrics_watchdog.h"

#include "video_rtsp.h"

#define C300X_SYSTEM_METRICS_CPU_WATCHDOG_PERCENT 90.0
#define C300X_SYSTEM_METRICS_CPU_WATCHDOG_SECONDS 300

static double double_abs(double value)
{
    return value < 0.0 ? -value : value;
}

static int metric_changed_percent(double previous, double current, int threshold_percent)
{
    double threshold = (double)threshold_percent;
    double diff = double_abs(current - previous);
    double baseline = double_abs(previous);

    if (threshold_percent <= 0) {
        return diff > 0.0;
    }
    if (baseline < 0.001) {
        return diff >= threshold;
    }
    return ((diff / baseline) * 100.0) >= threshold;
}

static int metric_changed_points(double previous, double current, int threshold_points)
{
    double threshold = (double)threshold_points;
    double diff = double_abs(current - previous);

    if (threshold_points <= 0) {
        return diff > 0.0;
    }
    return diff >= threshold;
}

int c300x_system_metrics_changed(
    const struct c300x_config *config,
    const struct system_metrics_sample *previous,
    const struct system_metrics_sample *current
)
{
    if (
        previous->has_cpu_usage != current->has_cpu_usage
        || (
            current->has_cpu_usage
            && metric_changed_points(
                previous->cpu_usage_percent,
                current->cpu_usage_percent,
                config->system_metrics_change_percent
            )
        )
    ) {
        return 1;
    }
    if (
        metric_changed_points(
            previous->load_1m_percent,
            current->load_1m_percent,
            config->system_metrics_change_percent
        )
        || metric_changed_points(
            previous->load_5m_percent,
            current->load_5m_percent,
            config->system_metrics_change_percent
        )
        || metric_changed_points(
            previous->load_15m_percent,
            current->load_15m_percent,
            config->system_metrics_change_percent
        )
    ) {
        return 1;
    }
    if (previous->has_memory != current->has_memory) {
        return 1;
    }
    if (
        current->has_memory
        && metric_changed_points(
            previous->memory_usage_percent,
            current->memory_usage_percent,
            config->system_metrics_change_percent
        )
    ) {
        return 1;
    }
    if (previous->has_temperature != current->has_temperature) {
        return 1;
    }
    if (
        current->has_temperature
        && metric_changed_percent(
            previous->temperature_c,
            current->temperature_c,
            config->system_metrics_change_percent
        )
    ) {
        return 1;
    }
    return 0;
}

void c300x_system_metrics_cpu_watchdog_apply(
    struct c300x_video *video,
    int has_cpu_usage,
    double cpu_usage_percent,
    time_t now,
    time_t *high_cpu_since,
    time_t *tripped_at
)
{
    struct c300x_video_status status;

    if (high_cpu_since == NULL || tripped_at == NULL || !has_cpu_usage) {
        return;
    }
    if (cpu_usage_percent < C300X_SYSTEM_METRICS_CPU_WATCHDOG_PERCENT) {
        *high_cpu_since = 0;
        *tripped_at = 0;
        return;
    }
    if (*high_cpu_since <= 0) {
        *high_cpu_since = now;
        return;
    }
    if (
        *tripped_at > 0
        || now - *high_cpu_since < C300X_SYSTEM_METRICS_CPU_WATCHDOG_SECONDS
    ) {
        return;
    }

    *tripped_at = now;
    if (video == NULL) {
        return;
    }

    c300x_video_status(video, &status);
    if (status.ring_call_active || status.ring_media_active) {
        c300x_video_doorbell_call_hangup(video);
        return;
    }
    if (status.home_call_running || status.home_call_active) {
        c300x_video_home_call_stop(video);
        return;
    }
    if (
        !status.external_media_active
        && (
            status.call_active
            || status.media_starting
            || status.bridge_media_active
            || status.clients > 0
        )
    ) {
        c300x_video_stop(video);
    }
}
