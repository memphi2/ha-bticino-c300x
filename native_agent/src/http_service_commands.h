#ifndef C300X_HTTP_SERVICE_COMMANDS_H
#define C300X_HTTP_SERVICE_COMMANDS_H

#include "http_maintenance.h"

typedef int (*c300x_schedule_command_fn)(const char *, const char *, int);
typedef void (*c300x_reboot_reply_fn)(int, int, void *);
/* Takes ownership of context, also on immediate failure. Reply runs only on
 * completion, never cancellation. The caller keeps its own response contract. */
void c300x_http_service_reboot(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, c300x_schedule_command_fn schedule,
    c300x_reboot_reply_fn reply, void *context, void (*destroy)(void *));
/* Preserve GET's status contract by waiting in an existing input slot instead
 * of adding a busy error or allocating another command/queue. */
int c300x_http_service_commands_defer(const struct c300x_http_maintenance *owner,
    const struct c300x_config *config, const struct request *request);
int c300x_http_service_commands_route(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, const struct request *request,
    c300x_schedule_command_fn schedule);

#endif
