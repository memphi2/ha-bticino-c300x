#ifndef C300X_DEVICE_USER_LABEL_H
#define C300X_DEVICE_USER_LABEL_H

/* Trim ASCII white space in place; returns the first kept character. */
const char *c300x_label_trim(char *value);

/* Whether a Qt 5 status confirms the label on a running, active overlay. */
int c300x_label_qt5_state_ok(const char *body, int applying);

/* Whether a label apply/restore by the patch script succeeded. */
int c300x_label_result_ok(char *output, int applying);

#endif
