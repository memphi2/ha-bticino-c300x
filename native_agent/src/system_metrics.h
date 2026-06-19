#ifndef C300X_SYSTEM_METRICS_H
#define C300X_SYSTEM_METRICS_H

#include <stddef.h>

#include "system_metrics_watchdog.h"

int c300x_system_metrics_read_sample(
    struct system_metrics_sample *sample,
    const struct system_metrics_sample *previous
);
int c300x_system_metrics_json(
    const struct system_metrics_sample *sample,
    int include_ok,
    char *body,
    size_t body_len
);

#endif
