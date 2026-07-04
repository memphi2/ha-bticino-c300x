#include "time_util.h"

#include <stddef.h>
#include <sys/time.h>

long long c300x_monotonic_ms(void)
{
    struct timeval now;

    gettimeofday(&now, NULL);
    return ((long long)now.tv_sec * 1000LL) + ((long long)now.tv_usec / 1000LL);
}
