#ifndef C300X_MEMO_DELETED_H
#define C300X_MEMO_DELETED_H

#include <stddef.h>

/* The last memos deleted through the agent, as memos[].id ("text/memo_12").
 * The display drops a stock memo only once its id is listed here, so one
 * deleted from Home Assistant leaves the station without a GUI restart. */
void c300x_memo_deleted_add(const char *kind, const char *name);
/* A memo with this id exists again: it is no longer deleted. */
void c300x_memo_deleted_seen(const char *kind, const char *name);
/* Closes the memos array and the object: ],"deleted":[...]}\n */
int c300x_memo_deleted_finish_json(char *body, size_t body_len, size_t *used);

#endif
