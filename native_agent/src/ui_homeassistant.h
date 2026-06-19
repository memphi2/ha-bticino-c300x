#ifndef C300X_UI_HOMEASSISTANT_H
#define C300X_UI_HOMEASSISTANT_H

#include <stddef.h>

enum c300x_ui_homeassistant_payload_result {
    C300X_UI_HOMEASSISTANT_PAYLOAD_OK = 0,
    C300X_UI_HOMEASSISTANT_PAYLOAD_UNSUPPORTED,
    C300X_UI_HOMEASSISTANT_PAYLOAD_INVALID_ACTION_ID,
    C300X_UI_HOMEASSISTANT_PAYLOAD_TOO_LARGE
};

enum c300x_ui_homeassistant_payload_result c300x_ui_homeassistant_build_payload(
    const char *query,
    char *payload,
    size_t payload_len
);

#endif
