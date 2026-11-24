#ifndef C300X_MDNS_H
#define C300X_MDNS_H

#include "c300x_agent.h"

#include <stdint.h>
#include <time.h>

/* HA renews its registration every 300 s: three missed renewals mean it can
 * no longer reach the station, for example after an address change. */
#define C300X_MDNS_HOME_ASSISTANT_QUIET_MS 900000LL

struct c300x_mdns {
    int fd;
    time_t next_announce_at;
    int announced;
    int wanted;
    uint32_t ipv4;
    char instance_id[33];
    char device_id[64]; /* Read once from the interface MAC. */
    long long last_response_ms;
};

long long c300x_mdns_home_assistant_present_ms(
    int connected_this_run,
    long long last_request_ms,
    long long now_ms
);
void c300x_mdns_init(struct c300x_mdns *mdns);
void c300x_mdns_close(struct c300x_mdns *mdns);
void c300x_mdns_open_if_needed(
    struct c300x_mdns *mdns,
    const struct c300x_config *config,
    int home_assistant_connected,
    int network_online,
    time_t now
);
int c300x_mdns_fd(const struct c300x_mdns *mdns);
int c300x_mdns_poll_timeout_ms(const struct c300x_mdns *mdns, time_t now);
void c300x_mdns_handle_query(
    struct c300x_mdns *mdns,
    const struct c300x_config *config
);
void c300x_mdns_announce_if_due(
    struct c300x_mdns *mdns,
    const struct c300x_config *config,
    time_t now
);
void c300x_mdns_device_id(char *out, size_t out_len);

#endif
