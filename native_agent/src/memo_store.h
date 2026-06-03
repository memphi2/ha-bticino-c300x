#ifndef C300X_MEMO_STORE_H
#define C300X_MEMO_STORE_H

#include "c300x_agent.h"

#include <stddef.h>

int c300x_text_memo_create(
    const char *root,
    int max_memos,
    const unsigned char *text,
    size_t text_len,
    int read,
    char *entry_name,
    size_t entry_name_len,
    char *error,
    size_t error_len
);

#endif
