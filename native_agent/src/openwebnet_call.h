#ifndef C300X_OPENWEBNET_CALL_H
#define C300X_OPENWEBNET_CALL_H

#include "c300x_agent.h"

enum {
    C300X_OPENWEBNET_SEND,
    C300X_OPENWEBNET_SEQUENCE,
    C300X_OPENWEBNET_WRITE_READBACK,
};

/* One OpenWebNet exchange with everything it needs and returns, so it can
 * run away from the thread that asked for it. */
struct c300x_openwebnet_call {
    int kind;
    char host[C300X_MAX_HOST_LEN];
    int port;
    int timeout_ms;
    char first[C300X_MAX_FRAME_LEN];
    char second[C300X_MAX_FRAME_LEN];
    int delay_ms;
    int ok;
    char reply[C300X_MAX_FRAME_LEN];
    char readback[C300X_MAX_FRAME_LEN];
    char error[C300X_MAX_ERROR_LEN];
};

/* Nonzero: the hook filled in the result, or deferred the call and left it
 * failed with an empty error. Zero: the caller runs the call itself. Set and
 * consulted on the HTTP loop thread only. */
typedef int (*c300x_openwebnet_hook_fn)(struct c300x_openwebnet_call *call);
extern c300x_openwebnet_hook_fn c300x_openwebnet_hook;
/* Called on the loop thread before a call runs there; waits for a worker. */
extern void (*c300x_openwebnet_before_inline)(void);

/* Set by a hook that deferred a call. The caller of the OpenWebNet client
 * then has to return at once, without an answer or any other effect: it is
 * called again and gets the result from the same call. */
extern int c300x_openwebnet_call_deferred;
int c300x_openwebnet_deferred(void);

void c300x_openwebnet_execute(struct c300x_openwebnet_call *call);
/* The same exchange: kind, target, commands and delay. */
int c300x_openwebnet_call_same(const struct c300x_openwebnet_call *left, const struct c300x_openwebnet_call *right);
void c300x_openwebnet_call_copy_result(struct c300x_openwebnet_call *call, const struct c300x_openwebnet_call *result);
/* Fill in a failure without an exchange; returns nonzero for a hook. */
int c300x_openwebnet_call_fail(struct c300x_openwebnet_call *call, const char *error);

#endif
