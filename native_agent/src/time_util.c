#include "time_util.h"

#include <time.h>

long long c300x_monotonic_ms(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        return 0;
    }
    return ((long long)now.tv_sec * 1000LL) + ((long long)now.tv_nsec / 1000000LL);
}
