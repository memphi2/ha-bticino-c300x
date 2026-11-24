#include "memo_vendor.h"

#include "memo_store.h"
#include "string_util.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MEMO_VENDOR_ACK "*#*1##"
#define MEMO_VENDOR_NACK "*#*0##"
#define MEMO_VENDOR_TEXT_LIST "*#8**100#3##"
#define MEMO_VENDOR_TEXT_LIST_REPLY "*#8**100#3"
#define MEMO_VENDOR_MAX_IDS 128

/* The client whose message.txt is written, until its request is answered. */
static int staged_fd = -1;

static void set_error(char *error, size_t error_len, const char *value)
{
    if (error_len > 0) {
        c300x_copy_string(error, error_len, value);
    }
}

/* Sends one command; DONE only when the station acknowledged it. */
static int exchange(const struct c300x_config *config, const char *command, char *error, size_t error_len)
{
    char reply[C300X_MAX_FRAME_LEN];

    if (!c300x_openwebnet_send(config, command, reply, sizeof(reply), error, error_len)) {
        return C300X_MEMO_VENDOR_FAILED;
    }
    return strcmp(reply, MEMO_VENDOR_ACK) == 0 ? C300X_MEMO_VENDOR_DONE : C300X_MEMO_VENDOR_REFUSED;
}

int c300x_memo_vendor_delete(const struct c300x_config *config, int number, int directory,
                             char *error, size_t error_len)
{
    char command[64];

    if (number <= 0 || directory < 0) {
        set_error(error, error_len, "invalid_answering_delete_target");
        return C300X_MEMO_VENDOR_FAILED;
    }
    snprintf(command, sizeof(command), "*8*94#%d#%d##", number, directory);
    return exchange(config, command, error, error_len);
}

/* The station answers a list with *#8**100#3*<n>*<n>...## and an empty one with a NACK. */
static int list_text_memos(const struct c300x_config *config, int *numbers, int *count,
                           char *error, size_t error_len)
{
    char reply[C300X_MAX_FRAME_LEN];
    const char *cursor;

    *count = 0;
    if (!c300x_openwebnet_send(config, MEMO_VENDOR_TEXT_LIST, reply, sizeof(reply), error, error_len)) {
        return C300X_MEMO_VENDOR_FAILED;
    }
    if (strcmp(reply, MEMO_VENDOR_NACK) == 0) {
        return C300X_MEMO_VENDOR_DONE;
    }
    if (strncmp(reply, MEMO_VENDOR_TEXT_LIST_REPLY, strlen(MEMO_VENDOR_TEXT_LIST_REPLY)) != 0) {
        set_error(error, error_len, "memo_list_unreadable");
        return C300X_MEMO_VENDOR_FAILED;
    }
    cursor = reply + strlen(MEMO_VENDOR_TEXT_LIST_REPLY);
    while (*cursor == '*' && *count < MEMO_VENDOR_MAX_IDS) {
        char *end = NULL;
        long number = strtol(cursor + 1, &end, 10);
        if (end == cursor + 1 || number <= 0 || number > 99999) {
            break;
        }
        numbers[(*count)++] = (int)number;
        cursor = end;
    }
    if (strcmp(cursor, "##") != 0) {
        set_error(error, error_len, "memo_list_unreadable");
        return C300X_MEMO_VENDOR_FAILED;
    }
    return C300X_MEMO_VENDOR_DONE;
}

static int listed(const int *numbers, int count, int number)
{
    for (int index = 0; index < count; index++) {
        if (numbers[index] == number) {
            return 1;
        }
    }
    return 0;
}

/* The memo the save added. When the store was full the station dropped its
 * oldest memo and may have given the new one that number: the latest then. */
static int saved_number(const struct c300x_memo_vendor_text *memo, const int *before, int before_count,
                        const int *after, int after_count)
{
    int added = 0;
    int found = 0;

    for (int index = 0; index < after_count; index++) {
        if (!listed(before, before_count, after[index])) {
            added = after[index];
            found++;
        }
    }
    return found == 1 ? added : c300x_text_memo_newest(memo->text_root, after, after_count);
}

static int deferred(int result, const char *error)
{
    return result == C300X_MEMO_VENDOR_FAILED && error[0] == '\0';
}

static int answered(const struct c300x_memo_vendor_text *memo, int result, const char *error)
{
    if (!deferred(result, error) && staged_fd == memo->client_fd) {
        staged_fd = -1;
    }
    return result;
}

int c300x_memo_vendor_create_text(const struct c300x_config *config, struct c300x_memo_vendor_text *memo,
                                  char *error, size_t error_len)
{
    int before[MEMO_VENDOR_MAX_IDS];
    int after[MEMO_VENDOR_MAX_IDS];
    int before_count = 0;
    int after_count = 0;
    int result;

    if (error_len > 0) {
        error[0] = '\0';
    }
    if (!memo->owns && staged_fd == memo->client_fd) {
        /* A new request on this connection: the earlier one was answered. */
        staged_fd = -1;
    }
    /* The first call makes the request the worker's owner, so no other
     * request's save is out while message.txt is written. */
    result = list_text_memos(config, before, &before_count, error, error_len);
    if (result != C300X_MEMO_VENDOR_DONE) {
        return answered(memo, result, error);
    }
    if (staged_fd != memo->client_fd) {
        if (!c300x_text_memo_stage(memo->records_dir, memo->text_root, memo->text, memo->text_len,
                                   error, error_len)) {
            return C300X_MEMO_VENDOR_FAILED;
        }
        staged_fd = memo->client_fd;
    }
    result = exchange(config, "*8*87#4*##", error, error_len);
    if (deferred(result, error)) {
        return result;
    }
    if (result != C300X_MEMO_VENDOR_DONE) {
        c300x_text_memo_unstage(memo->records_dir);
        return answered(memo, result, error);
    }
    result = list_text_memos(config, after, &after_count, error, error_len);
    if (result != C300X_MEMO_VENDOR_DONE) {
        return answered(memo, result, error);
    }
    memo->number = saved_number(memo, before, before_count, after, after_count);
    if (memo->number <= 0) {
        set_error(error, error_len, "memo_create_unconfirmed");
        return answered(memo, C300X_MEMO_VENDOR_FAILED, error);
    }
    memo->read_set = 0;
    if (memo->read) {
        char command[64];
        char status[64];
        char reply[C300X_MAX_FRAME_LEN];

        /* The station answers with the new state, then an ACK. */
        snprintf(command, sizeof(command), "*#8**#101#3#%d*1##", memo->number);
        snprintf(status, sizeof(status), "*#8**101#3#%d*1##", memo->number);
        if (!c300x_openwebnet_send(config, command, reply, sizeof(reply), error, error_len)) {
            if (error[0] == '\0') {
                return C300X_MEMO_VENDOR_FAILED;
            }
            reply[0] = '\0';
        }
        memo->read_set = strcmp(reply, status) == 0 || strcmp(reply, MEMO_VENDOR_ACK) == 0;
        if (error_len > 0) {
            error[0] = '\0';
        }
    }
    return answered(memo, C300X_MEMO_VENDOR_DONE, error);
}

void c300x_memo_vendor_create_text_abort(const struct c300x_memo_vendor_text *memo)
{
    if (staged_fd == memo->client_fd) {
        staged_fd = -1;
        c300x_text_memo_unstage(memo->records_dir);
    }
}
