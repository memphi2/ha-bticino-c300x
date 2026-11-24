#ifndef C300X_MEMO_STORE_H
#define C300X_MEMO_STORE_H

#include "c300x_agent.h"

#include <stddef.h>

void c300x_read_voicemail_info(const char *path, int *read, char *date, size_t size, long long *unix_time);

/* Checks and normalizes a memo text in place; zero when it is not one. */
int c300x_text_memo_normalize(unsigned char *text, size_t *text_len);
/* Writes message.txt for bt_answering_machine, owned like owner_path. */
int c300x_text_memo_stage(const char *records_dir, const char *owner_path,
                          const unsigned char *text, size_t text_len, char *error, size_t error_len);
void c300x_text_memo_unstage(const char *records_dir);
/* The number among numbers whose msg_info.ini holds the latest UnixTime. */
int c300x_text_memo_newest(const char *root, const int *numbers, int count);

#endif
