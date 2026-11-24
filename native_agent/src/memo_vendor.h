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

/* One text memo, saved the way the station GUI saves one. */
struct c300x_memo_vendor_text {
    int client_fd;
    /* The request owns the OpenWebNet worker (its first call is out). */
    int owns;
    const char *records_dir;
    const char *text_root;
    const unsigned char *text;
    size_t text_len;
    int read;
    /* Set when DONE: the memo_N the station chose, and whether it is read. */
    int number;
    int read_set;
};

/* Lists the station's text memos, writes message.txt into the records
 * directory, has the station save it (*8*87#4*##) and lists again. The second
 * list names the new memo and also reaches the display, which adds it. A
 * request handled again does not write message.txt again. REFUSED: the
 * station would not save it; message.txt is removed. */
int c300x_memo_vendor_create_text(const struct c300x_config *config, struct c300x_memo_vendor_text *memo,
                                  char *error, size_t error_len);
/* The request ended before its save command went out. */
void c300x_memo_vendor_create_text_abort(const struct c300x_memo_vendor_text *memo);

#endif
