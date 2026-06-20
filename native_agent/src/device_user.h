#ifndef C300X_DEVICE_USER_H
#define C300X_DEVICE_USER_H

#include <stddef.h>

#include "c300x_agent.h"

#define C300X_DEVICE_USER_ACCOUNT "homeassistant"
#define C300X_DEVICE_USER_LABEL "Home Assistant"
#define C300X_DEVICE_USER_ERROR_LEN C300X_MAX_ERROR_LEN
#define C300X_DEVICE_USER_LABEL_LEN 96

struct c300x_device_user_status {
    int status_available;
    int supported;
    int domain_present;
    int homeassistant_user_present;
    int accounts_homeassistant_present;
    int route_int_homeassistant_present;
    int route_ext_homeassistant_present;
    int route_conf_homeassistant_present;
    int route_conf_is_symlink;
    int writable_files_present;
    int media_identity_available;
    int routes_consistent;
    char account_label[C300X_DEVICE_USER_LABEL_LEN];
    char error[C300X_DEVICE_USER_ERROR_LEN];
};

struct c300x_device_user_identity {
    char domain[128];
    char from_user[128];
    char from_aor[256];
    char to_aor[256];
};

int c300x_device_user_read_status(struct c300x_device_user_status *status);
int c300x_device_user_media_identity(
    const char *domain_hint,
    struct c300x_device_user_identity *identity
);
int c300x_device_user_ensure_homeassistant(
    struct c300x_device_user_status *status,
    const char *account_label,
    char *error,
    size_t error_len
);

#endif
