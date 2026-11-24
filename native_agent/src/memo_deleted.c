#include "memo_deleted.h"

#include "string_util.h"

#include <pthread.h>
#include <stdio.h>
#include <string.h>

#define MEMO_DELETED_KEEP 32

static pthread_mutex_t deleted_lock = PTHREAD_MUTEX_INITIALIZER;
static char deleted_ids[MEMO_DELETED_KEEP][48];
static size_t deleted_next;

static int memo_id(char *id, const char *kind, const char *name)
{
    return snprintf(id, sizeof(deleted_ids[0]), "%s/%s", kind, name) < (int)sizeof(deleted_ids[0]);
}

void c300x_memo_deleted_seen(const char *kind, const char *name)
{
    char id[sizeof(deleted_ids[0])];
    if (!memo_id(id, kind, name)) {
        return;
    }
    pthread_mutex_lock(&deleted_lock);
    for (size_t index = 0; index < MEMO_DELETED_KEEP; index++) {
        if (strcmp(deleted_ids[index], id) == 0) {
            deleted_ids[index][0] = '\0';
        }
    }
    pthread_mutex_unlock(&deleted_lock);
}

void c300x_memo_deleted_add(const char *kind, const char *name)
{
    char id[sizeof(deleted_ids[0])];
    if (!memo_id(id, kind, name)) {
        return;
    }
    c300x_memo_deleted_seen(kind, name);
    pthread_mutex_lock(&deleted_lock);
    memcpy(deleted_ids[deleted_next], id, sizeof(id));
    deleted_next = (deleted_next + 1) % MEMO_DELETED_KEEP;
    pthread_mutex_unlock(&deleted_lock);
}

int c300x_memo_deleted_finish_json(char *body, size_t body_len, size_t *used)
{
    int ok = c300x_appendf(body, body_len, used, "],\"deleted\":[");
    const char *separator = "";
    pthread_mutex_lock(&deleted_lock);
    for (size_t step = 0; ok && step < MEMO_DELETED_KEEP; step++) {
        const char *id = deleted_ids[(deleted_next + step) % MEMO_DELETED_KEEP];
        if (id[0] != '\0') {
            /* Kinds and memo_<n> names: nothing to escape. */
            ok = c300x_appendf(body, body_len, used, "%s\"%s\"", separator, id);
            separator = ",";
        }
    }
    pthread_mutex_unlock(&deleted_lock);
    return ok && c300x_appendf(body, body_len, used, "]}\n");
}
