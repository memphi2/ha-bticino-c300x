#ifndef C300X_MEMO_VENDOR_H
#define C300X_MEMO_VENDOR_H

#include "c300x_agent.h"

#include <stddef.h>

/* Directories of bt_answering_machine, the second number of its frames. */
#define C300X_ANSWERING_DIRECTORY_VIDEO_MESSAGE 0
#define C300X_ANSWERING_DIRECTORY_VOICE_MEMO 2
#define C300X_ANSWERING_DIRECTORY_TEXT_MEMO 3

/* Results of an exchange with bt_answering_machine. FAILED with an empty
 * error and c300x_openwebnet_deferred() set: the request runs again. */
enum {
    C300X_MEMO_VENDOR_REFUSED = -1,
    C300X_MEMO_VENDOR_FAILED = 0,
    C300X_MEMO_VENDOR_DONE = 1
};

/* Asks the station to delete one stored entry. It refuses (NACK) an entry
 * that is not in the list it keeps in memory. */
int c300x_memo_vendor_delete(const struct c300x_config *config, int number, int directory,
                             char *error, size_t error_len);

#endif
