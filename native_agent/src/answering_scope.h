#ifndef C300X_ANSWERING_SCOPE_H
#define C300X_ANSWERING_SCOPE_H

#include "c300x_agent.h"
#include "http_request.h"

#include <stddef.h>

#define C300X_ANSWERING_UNSUPPORTED_MODEL "answering_machine_unsupported_model"

/* The C100X (SHARK board) has no answering machine: its HAL reports the
 * hardware flag 0xff, bt_answering_machine forces it off at start and records
 * nothing. Voice memos need a GUI recorder the C100X lacks. Text memos keep
 * reading and writing; memo delete stays off there, as HA offers it only with
 * the C300X Display patch. */
int c300x_answering_capabilities_json(const struct c300x_config *config, int c100x, char *out, size_t len);

/* On a C100X, answer 409 for the answering-machine, voice-memo audio and memo
 * delete routes before any device I/O. Returns 1 when it answered. */
int c300x_answering_route_refused(int client_fd, const struct request *request);

#endif
