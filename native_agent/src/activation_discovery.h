#ifndef C300X_ACTIVATION_DISCOVERY_H
#define C300X_ACTIVATION_DISCOVERY_H

#include "c300x_agent.h"
#include "outdoor_units.h"
#include "station_archive.h"

/* 16 configured and 33 station items of at most about 1.4 KiB each, escaped. */
#define C300X_ACTIVATIONS_JSON_SIZE (96 * 1024)

/* The activations the station itself knows (archive.xml, conf.xml): its
 * door locks on the bus, its actuators and its stair light. A configured
 * item with the same id, or of the same type at the same address, hides
 * one. */
struct c300x_activation_discovery {
    int loaded;
    char archive[12]; /* archive.xml: ok, empty, missing, unreadable; "" when not read */
    int count;
    struct c300x_activation items[C300X_MAX_DISCOVERED_ACTIVATIONS];
};

/* Pure: the items of the parsed station files. The stair light is at a
 * configured stairLightDefaultAddress, else at the station's own address
 * from conf.xml; without either it is not listed. */
void c300x_activation_discovery_build(struct c300x_activation_discovery *discovery,
                                      const struct c300x_station_archive *station, const char *archive_state,
                                      const struct c300x_config *config);
/* Reads the station files; no items while activations or station items are off. */
void c300x_activation_discover(const struct c300x_config *config, struct c300x_activation_discovery *discovery);
/* Pure: the GET /api/v1/activations body, configured items first; units
 * names each lock's outdoor unit (may be NULL). Zero when it does not fit. */
int c300x_activations_json(const struct c300x_config *config, const struct c300x_activation_discovery *discovery,
                           const struct c300x_outdoor_units *units, char *out, size_t out_len);

#endif
