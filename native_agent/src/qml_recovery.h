#ifndef C300X_QML_RECOVERY_H
#define C300X_QML_RECOVERY_H

#include "http_maintenance.h"

/* Agent start: finish a QML write that a crash, a power loss or a kill left
 * behind. A write-class job without a client: the QML write deadline and
 * grace period, and the maintenance slot stays busy until it has ended. */
void c300x_qml_recovery_start(struct c300x_http_maintenance *owner,
    const struct c300x_config *config);

#endif
