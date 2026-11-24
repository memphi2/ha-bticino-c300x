#ifndef C300X_HTTP_MAINTENANCE_H
#define C300X_HTTP_MAINTENANCE_H

#include "command_job.h"
#include "http_auth.h"

/* A QML write may take this long; past it, it gets SIGTERM and the grace
 * period for its rollback trap: files back, remount read-only, restart of the
 * previous GUI (two 2 s waits); about 8 s on the device at worst. */
#define C300X_QML_WRITE_TIMEOUT_MS 30000
#define C300X_QML_WRITE_TERM_GRACE_MS 15000

struct c300x_http_maintenance;
typedef void (*c300x_maintenance_write_fn)(void *, const char *, const char *);
/* Return zero only when a subsequent job was started for the same request. */
typedef int (*c300x_maintenance_complete_fn)(struct c300x_http_maintenance *);

struct c300x_http_maintenance {
    struct c300x_command_job job;
    int client_fd;
    int gui_reload;
    int records_write;
    char action[16];
    c300x_maintenance_write_fn record_write;
    void *write_context;
    c300x_maintenance_complete_fn complete;
    void *context;
    void (*destroy_context)(void *);
};

void c300x_http_maintenance_init(struct c300x_http_maintenance *owner,
    c300x_maintenance_write_fn record_write, void *context);
int c300x_http_maintenance_busy(const struct c300x_http_maintenance *owner);
int c300x_http_maintenance_prepare(const struct c300x_http_maintenance *owner, struct pollfd *fd);
void c300x_http_maintenance_tick(struct c300x_http_maintenance *owner);
void c300x_http_maintenance_close(struct c300x_http_maintenance *owner);
/* Called only after API admission; unrecognized routes retain the caller's fallback. */
int c300x_http_maintenance_route(struct c300x_http_maintenance *owner, int client_fd,
    const struct c300x_config *config, const struct request *request);

#endif
