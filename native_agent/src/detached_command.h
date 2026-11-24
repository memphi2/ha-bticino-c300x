#ifndef C300X_DETACHED_COMMAND_H
#define C300X_DETACHED_COMMAND_H

/* Runs program [argument] with only stdin/out/err open and default
 * SIGPIPE (the agent ignores it). delay_ms <= 0: waits for its exit, at
 * most C300X_DETACHED_COMMAND_WAIT_MS, and answers whether it succeeded.
 * delay_ms > 0: starts it after the delay in its own session, orphaned to
 * init (nothing left to reap), and answers whether that was started. */
int c300x_run_detached_command(const char *program, const char *argument, int delay_ms);

#endif
