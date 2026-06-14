#ifndef C300X_ACTIVATION_DISCOVERY_H
#define C300X_ACTIVATION_DISCOVERY_H

#include "c300x_agent.h"

struct c300x_activation_discovery {
    int available;
    int truncated;
    int scanned_files;
    int count;
    struct c300x_activation items[C300X_MAX_DISCOVERED_ACTIVATIONS];
};

void c300x_activation_discovery_reset(struct c300x_activation_discovery *discovery);
void c300x_activation_discover(
    const struct c300x_config *config,
    struct c300x_activation_discovery *discovery
);

#endif
