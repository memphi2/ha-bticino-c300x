#ifndef C300X_TIME_UTIL_H
#define C300X_TIME_UTIL_H

#include <time.h>

long long c300x_monotonic_ms(void);

/* Whole seconds for timers that must not follow wall-clock steps (NTP sync
 * after boot, a manual date change); never 0, which timers read as unset. */
static inline time_t c300x_monotonic_seconds(void)
{
    return (time_t)(c300x_monotonic_ms() / 1000) + 1;
}

#endif
