#ifndef C100X_GUI_RESPONSE_H
#define C100X_GUI_RESPONSE_H

/* Read a bounded probe response from stdin; never contacts a device/service. */
int c100x_gui_response_cli(const char *mode, const char *generation, const char *probe);
int c100x_gui_readiness_validate(const char *body, const char *generation, const char *probe);

#endif
