#ifndef C300X_PICTURE_SOURCE_H
#define C300X_PICTURE_SOURCE_H

#include "picture_control.h"

enum picture_source_result {
    PICTURE_SOURCE_OK, PICTURE_SOURCE_UNAVAILABLE, PICTURE_SOURCE_NOT_APPLIED
};

/* Eligibility only. Advertise direct control only after an active READ succeeds. */
int picture_source_supported(const char *model, const char *firmware);

/* Worker only. Caller binds active() to the original session and its deadline.
 * On success values are brightness, contrast, saturation in stock UI percent. */
enum picture_source_result picture_source_execute(const struct picture_command *command,
    int values[3], int (*active)(void *), void *ctx);

#endif
