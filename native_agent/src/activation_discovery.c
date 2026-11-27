#include "activation_discovery.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "activations.h"
#include "json_util.h"
#include "string_util.h"

static int hidden_by_config(const struct c300x_config *config, const struct c300x_activation *item)
{
    for (int index = 0; index < config->activations_count; index++) {
        const struct c300x_activation *existing = &config->activations[index];
        if (strcmp(existing->id, item->id) == 0
            || (strcmp(existing->type, item->type) == 0 && strcmp(existing->address, item->address) == 0)) {
            return 1;
        }
    }
    return 0;
}

/* id: prefix and the address with '_' for '#'; an item whose id or
 * address does not fit is left out. */
static void add_item(struct c300x_activation_discovery *discovery, const struct c300x_config *config,
                     const char *type, const char *prefix, const char *where, const char *name,
                     const char *fallback_name)
{
    struct c300x_activation *item;

    if (discovery->count >= C300X_MAX_DISCOVERED_ACTIVATIONS || !c300x_unit_where_valid(where)
        || strlen(where) >= sizeof(item->address)
        || strlen(prefix) + strlen(where) >= sizeof(item->id)) {
        return;
    }
    item = &discovery->items[discovery->count];
    memset(item, 0, sizeof(*item));
    snprintf(item->id, sizeof(item->id), "%s%s", prefix, prefix[strlen(prefix) - 1] == '_' ? where : "");
    for (char *p = item->id; *p != '\0'; p++) {
        if (*p == '#') {
            *p = '_';
        }
    }
    c300x_copy_string(item->type, sizeof(item->type), type);
    c300x_copy_string(item->address_mode, sizeof(item->address_mode), "manual");
    c300x_copy_string(item->address, sizeof(item->address), where);
    if (name[0] != '\0') {
        c300x_copy_string(item->name, sizeof(item->name), name);
    } else {
        snprintf(item->name, sizeof(item->name), "%s %s", fallback_name, where);
    }
    if (!hidden_by_config(config, item)) {
        discovery->count++;
    }
}

void c300x_activation_discovery_build(struct c300x_activation_discovery *discovery,
                                      const struct c300x_station_archive *station, const char *archive_state,
                                      const struct c300x_config *config)
{
    memset(discovery, 0, sizeof(*discovery));
    discovery->loaded = 1;
    c300x_copy_string(discovery->archive, sizeof(discovery->archive), archive_state);
    if (strcmp(archive_state, "ok") == 0 && station->unit_count + station->lock_count
            + station->actuator_count == 0 && !station->stair_light) {
        c300x_copy_string(discovery->archive, sizeof(discovery->archive), "empty");
    }
    for (int index = 0; index < station->lock_count; index++) {
        add_item(discovery, config, "lock", "station_lock_", station->locks[index].where,
                 station->locks[index].name, "Door lock");
    }
    for (int index = 0; index < station->actuator_count; index++) {
        add_item(discovery, config, "actuator", "station_actuator_", station->actuators[index].where,
                 station->actuators[index].name, "Actuator");
    }
    if (station->stair_light) {
        const char *where = station->own_where[0] != '\0' ? station->own_where : config->stair_light_default_address;
        add_item(discovery, config, "stair_light", "station_stair_light", where, station->stair_light_name,
                 "Stair light");
    }
}

void c300x_activation_discover(const struct c300x_config *config, struct c300x_activation_discovery *discovery)
{
    static const struct c300x_station_archive nothing;
    const char *archive_state = "unreadable";
    struct c300x_station_archive *station;

    if (!config->activations_enabled || !config->activations_auto_discover) {
        memset(discovery, 0, sizeof(*discovery));
        discovery->loaded = 1;
        return;
    }
    station = malloc(sizeof(*station));
    if (station == NULL) {
        c300x_activation_discovery_build(discovery, &nothing, archive_state, config);
        return;
    }
    c300x_station_archive_load(station, C300X_ARCHIVE_XML_PATH, C300X_CONF_XML_PATH, &archive_state);
    c300x_activation_discovery_build(discovery, station, archive_state, config);
    free(station);
}

/* A lock's outdoor unit: the unit whose door lock is at this address. */
static const char *lock_unit(const struct c300x_outdoor_units *units, const struct c300x_activation *activation)
{
    int index = units != NULL && strcmp(activation->type, "lock") == 0 && activation->address[0] != '\0'
        ? c300x_outdoor_units_find_lock(units, activation->address) : -1;

    return index >= 0 ? units->items[index].id : NULL;
}

static int append_item(char *out, size_t out_len, size_t *used, const struct c300x_activation *activation,
                       const char *source, const char *unit, int first)
{
    char id[C300X_JSON_QUOTED_LEN(C300X_MAX_ACTIVATION_ID_LEN)];
    char name[C300X_JSON_QUOTED_LEN(C300X_MAX_ACTIVATION_NAME_LEN)];
    char type[C300X_JSON_QUOTED_LEN(C300X_MAX_ACTIVATION_TYPE_LEN)];
    char address_mode[C300X_JSON_QUOTED_LEN(C300X_MAX_ACTIVATION_ADDRESS_MODE_LEN)];
    char address[C300X_JSON_QUOTED_LEN(C300X_MAX_ADDRESS_LEN)];
    char unit_json[C300X_JSON_QUOTED_LEN(C300X_UNIT_WHERE_LEN)];

    return c300x_appendf(out, out_len, used,
        "%s{\"id\":%s,\"name\":%s,\"type\":%s,\"addressMode\":%s,\"address\":%s,\"source\":\"%s\","
        "\"executable\":%s,\"unit\":%s}",
        first ? "" : ",",
        c300x_json_string(activation->id, id, sizeof(id)),
        c300x_json_string(activation->name, name, sizeof(name)),
        c300x_json_string(activation->type, type, sizeof(type)),
        c300x_json_string(activation->address_mode, address_mode, sizeof(address_mode)),
        c300x_json_string(activation->address, address, sizeof(address)),
        source,
        c300x_activation_is_executable(activation) ? "true" : "false",
        c300x_json_string_or_null(unit, unit_json, sizeof(unit_json)));
}

int c300x_activations_json(const struct c300x_config *config, const struct c300x_activation_discovery *discovery,
                           const struct c300x_outdoor_units *units, char *out, size_t out_len)
{
    size_t used = 0;
    int enabled = config->activations_enabled;
    int station = enabled && config->activations_auto_discover;
    int count = enabled ? config->activations_count + (station ? discovery->count : 0) : 0;
    int emitted = 0;
    char archive[24] = "null";

    if (station && discovery->archive[0] != '\0') {
        snprintf(archive, sizeof(archive), "\"%s\"", discovery->archive);
    }
    if (!c300x_appendf(out, out_len, &used,
            "{\"ok\":true,\"enabled\":%s,\"supported\":%s,\"auto_discover\":%s,\"station\":%s,\"count\":%d,\"items\":[",
            enabled ? "true" : "false", count > 0 ? "true" : "false", station ? "true" : "false", archive, count)) {
        return 0;
    }
    for (int index = 0; enabled && index < config->activations_count; index++) {
        if (!append_item(out, out_len, &used, &config->activations[index], "config",
                         lock_unit(units, &config->activations[index]), emitted++ == 0)) {
            return 0;
        }
    }
    for (int index = 0; station && index < discovery->count; index++) {
        if (!append_item(out, out_len, &used, &discovery->items[index], "station",
                         lock_unit(units, &discovery->items[index]), emitted++ == 0)) {
            return 0;
        }
    }
    return c300x_appendf(out, out_len, &used, "]}\n");
}
