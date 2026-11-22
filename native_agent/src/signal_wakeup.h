#ifndef C300X_SIGNAL_WAKEUP_H
#define C300X_SIGNAL_WAKEUP_H

/* A process-lifetime, nonblocking wake pipe, reused across server runs. */
int c300x_signal_wakeup_init(void);
void c300x_signal_wakeup_drain(void);

/* Async-signal-safe; preserves errno and never waits for pipe capacity. */
void c300x_signal_wakeup_notify(void);

#endif
