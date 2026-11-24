#include "memo_vendor.h"

#include "string_util.h"

#include <stdio.h>
#include <string.h>

#define MEMO_VENDOR_ACK "*#*1##"

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
