#ifndef C300X_SYSTEM_METRICS_WATCHDOG_H
#define C300X_SYSTEM_METRICS_WATCHDOG_H

#include <time.h>

#include "c300x_agent.h"

struct c300x_video;

struct system_metrics_sample {
    long cpu_count;
    unsigned long long cpu_total_jiffies;
    unsigned long long cpu_idle_jiffies;
    int has_cpu_jiffies;
    int has_cpu_usage;
    double cpu_usage_percent;
    double load_1m;
    double load_5m;
    double load_15m;
    double load_1m_percent;
    double load_5m_percent;
    double load_15m_percent;
    int has_memory;
    long memory_total_kb;
    long memory_available_kb;
    long memory_used_kb;
    double memory_usage_percent;
    int has_temperature;
    double temperature_c;
    char temperature_source[C300X_MAX_PATH_LEN];
};

int c300x_system_metrics_changed(
    const struct c300x_config *config,
    const struct system_metrics_sample *previous,
    const struct system_metrics_sample *current
);
void c300x_system_metrics_cpu_watchdog_apply(
    struct c300x_video *video,
    int has_cpu_usage,
    double cpu_usage_percent,
    time_t now,
    time_t *high_cpu_since,
    time_t *tripped_at
);

#endif
