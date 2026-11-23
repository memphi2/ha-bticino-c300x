#ifndef C300X_HTTP_UI_PREFERENCES_H
#define C300X_HTTP_UI_PREFERENCES_H

#include "c300x_agent.h"
#include "http_request.h"

/* /ui/preferences: the display's own settings, loopback and GUI header only. */
void c300x_http_ui_preferences(int fd, struct c300x_config *config, const struct request *request, int loopback);

#endif
