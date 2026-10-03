#ifndef C300X_SYSTEM_METRICS_MONITOR_H
#define C300X_SYSTEM_METRICS_MONITOR_H

#include "system_metrics.h"

struct c300x_system_metrics_monitor {
    struct system_metrics_sample last;
    struct system_metrics_sample last_delivered;
    int initialized;
    int delivered_initialized;
    int delivery_pending;
    long long next_sample_ms;
    long long last_delivered_ms;
    time_t last_delivered_at;
    time_t high_cpu_since;
    time_t watchdog_tripped_at;
};

int c300x_system_metrics_monitor_init(
    const struct c300x_config *config,
    struct c300x_system_metrics_monitor *monitor
);
int c300x_system_metrics_monitor_timeout_ms(const struct c300x_system_metrics_monitor *monitor);
int c300x_system_metrics_monitor_tick(
    const struct c300x_config *config,
    struct c300x_system_metrics_monitor *monitor,
    struct c300x_video *video,
    time_t now
);
void c300x_system_metrics_monitor_delivered(struct c300x_system_metrics_monitor *monitor, time_t now);

#endif
