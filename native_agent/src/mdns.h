#ifndef C300X_MDNS_H
#define C300X_MDNS_H

#include "c300x_agent.h"

#include <time.h>

struct c300x_mdns {
    int fd;
    time_t next_announce_at;
    int announced;
};

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
time_t c300x_mdns_next_announce_at(const struct c300x_mdns *mdns);
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
