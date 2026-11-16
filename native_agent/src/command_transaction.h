#ifndef C300X_COMMAND_TRANSACTION_H
#define C300X_COMMAND_TRANSACTION_H

#include <stddef.h>

/* Synchronous file transaction: bounded output, but no kill or exit deadline.
 * The caller must let the script commit/roll back before processing shutdown. */
int c300x_command_transaction_capture(const char *program, const char *argument,
    char *out, size_t out_len);

#endif
