#include "qml_recovery.h"

#include <unistd.h>

void c300x_qml_recovery_start(struct c300x_http_maintenance *owner,
    const struct c300x_config *config)
{
    const char *program = config->maintenance_qml_patch_script;
    if (config->maintenance_qml_patch_enabled && !c300x_http_maintenance_busy(owner)
        && access(program, X_OK) == 0
        && c300x_command_job_start(&owner->job, program, "recover", -1, C300X_QML_WRITE_TIMEOUT_MS)) {
        owner->job.term_grace_ms = C300X_QML_WRITE_TERM_GRACE_MS;
    }
}
