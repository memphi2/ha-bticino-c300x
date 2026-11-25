#ifndef C300X_MAINTENANCE_JOB_LIMIT_H
#define C300X_MAINTENANCE_JOB_LIMIT_H

#include "c300x_agent.h"
#include "http_maintenance.h"

/* The job limit of a maintenance script. QML writes may need both a failed
 * start and a restored-GUI restart. A GUI restart on the Qt 5 display
 * (firmware 3.0.x) waits for the old display program to end first; on Qt 4
 * it keeps the short limit. */
static inline int c300x_maintenance_job_timeout_ms(int records_write, int gui_reload)
{
    int long_job = gui_reload ? c300x_device_display_is_qt5() : records_write;
    return long_job ? C300X_QML_WRITE_TIMEOUT_MS : 10000;
}

#endif
