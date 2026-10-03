#include "system_metrics_monitor.h"

#include <limits.h>
#include <string.h>

int c300x_system_metrics_monitor_init(
    const struct c300x_config *config,
    struct c300x_system_metrics_monitor *monitor
)
{
    memset(monitor, 0, sizeof(*monitor));
    if (!config->system_metrics_enabled || !config->system_metrics_watch) {
        return 1;
    }
    c300x_system_metrics_read_sample(&monitor->last, NULL);
    if (!c300x_system_metrics_instance_id(monitor->last.instance_id, sizeof(monitor->last.instance_id))) {
        return 0;
    }
    monitor->last.sample_interval_seconds = config->system_metrics_sample_interval_seconds;
    monitor->last.heartbeat_seconds = config->system_metrics_heartbeat_seconds;
    monitor->initialized = 1;
    monitor->next_sample_ms = monitor->last.sampled_monotonic_ms + config->system_metrics_sample_interval_seconds * 1000LL;
    return 1;
}

int c300x_system_metrics_monitor_timeout_ms(const struct c300x_system_metrics_monitor *monitor)
{
    if (!monitor->initialized) {
        return -1;
    }
    long long remaining = monitor->next_sample_ms - c300x_system_metrics_monotonic_ms();
    return remaining <= 0 ? 0 : remaining > INT_MAX ? INT_MAX : (int)remaining;
}

void c300x_system_metrics_monitor_delivered(struct c300x_system_metrics_monitor *monitor, time_t now)
{
    monitor->last_delivered = monitor->last;
    monitor->delivered_initialized = 1;
    monitor->last_delivered_at = now;
    monitor->last_delivered_ms = c300x_system_metrics_monotonic_ms();
    monitor->delivery_pending = 0;
}

int c300x_system_metrics_monitor_tick(
    const struct c300x_config *config,
    struct c300x_system_metrics_monitor *monitor,
    struct c300x_video *video,
    time_t now
)
{
    struct system_metrics_sample sample;
    long long now_ms = c300x_system_metrics_monotonic_ms();
    if (!monitor->initialized || !config->system_metrics_enabled || !config->system_metrics_watch
        || monitor->next_sample_ms > now_ms) {
        return 0;
    }
    monitor->next_sample_ms = now_ms + config->system_metrics_sample_interval_seconds * 1000LL;
    c300x_system_metrics_read_sample(&sample, &monitor->last);
    monitor->last = sample;
    c300x_system_metrics_cpu_watchdog_apply(
        video, sample.has_cpu_usage, sample.cpu_usage_percent, now,
        &monitor->high_cpu_since, &monitor->watchdog_tripped_at
    );
    return !monitor->delivered_initialized || monitor->delivery_pending
        || now_ms - monitor->last_delivered_ms >= config->system_metrics_heartbeat_seconds * 1000LL
        || c300x_system_metrics_changed(config, &monitor->last_delivered, &sample)
        || (sample.has_cpu_usage && sample.cpu_usage_percent >= 90.0);
}
