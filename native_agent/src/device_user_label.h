#ifndef C300X_DEVICE_USER_LABEL_H
#define C300X_DEVICE_USER_LABEL_H

/* Trim ASCII white space in place; returns the first kept character. */
const char *c300x_label_trim(char *value);

/* Whether a label apply/restore by the patch script succeeded. */
int c300x_label_result_ok(char *output, int applying);

#endif
