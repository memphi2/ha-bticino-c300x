#include "ui_homeassistant.h"

#include "http_util.h"

#include <stdio.h>
#include <string.h>

#define C300X_DASHBOARD_DOMAIN "c300x"
#define C300X_DASHBOARD_STAIR_LIGHT_ENTITY "stair_light"

static int json_escape_string(const char *value, char *out, size_t out_len)
{
    size_t used = 0;

    if (out_len == 0) {
        return 0;
    }
    for (size_t index = 0; value[index] != '\0'; index++) {
        unsigned char ch = (unsigned char)value[index];

        if (ch == '\\' || ch == '"') {
            if (used + 2 >= out_len) {
                return 0;
            }
            out[used++] = '\\';
            out[used++] = (char)ch;
            continue;
        }
        if (ch < 0x20) {
            int written;

            if (used + 6 >= out_len) {
                return 0;
            }
            written = snprintf(out + used, out_len - used, "\\u%04x", ch);
            if (written != 6) {
                return 0;
            }
            used += 6;
            continue;
        }
        if (used + 1 >= out_len) {
            return 0;
        }
        out[used++] = (char)ch;
    }
    out[used] = '\0';
    return 1;
}

static int json_string(const char *value, char *out, size_t out_len)
{
    size_t value_len;

    if (out_len < 3) {
        return 0;
    }
    out[0] = '"';
    if (!json_escape_string(value != NULL ? value : "", out + 1, out_len - 2)) {
        return 0;
    }
    value_len = strlen(out + 1);
    if (value_len + 2 >= out_len) {
        return 0;
    }
    out[value_len + 1] = '"';
    out[value_len + 2] = '\0';
    return 1;
}

static char *first_entity_id(char *entities)
{
    char *comma = strchr(entities, ',');
    char *trimmed = entities;

    if (comma != NULL) {
        *comma = '\0';
    }
    while (*trimmed == ' ') {
        trimmed++;
    }
    return trimmed;
}

static enum c300x_ui_homeassistant_payload_result build_dashboard_action_payload(
    const char *entity_id,
    const char *option,
    char *payload,
    size_t payload_len
)
{
    int written;

    if (!validate_action_id(entity_id)) {
        return C300X_UI_HOMEASSISTANT_PAYLOAD_INVALID_ACTION_ID;
    }
    if (strcmp(entity_id, C300X_DASHBOARD_STAIR_LIGHT_ENTITY) == 0) {
        written = snprintf(payload, payload_len, "{\"type\":\"stair_light\"}");
    } else if (option[0] != '\0') {
        char option_json[1024];

        if (!json_string(option, option_json, sizeof(option_json))) {
            return C300X_UI_HOMEASSISTANT_PAYLOAD_TOO_LARGE;
        }
        written = snprintf(
            payload,
            payload_len,
            "{\"type\":\"dashboard_action\",\"entity_id\":\"%s\",\"option\":%s}",
            entity_id,
            option_json
        );
    } else {
        written = snprintf(
            payload,
            payload_len,
            "{\"type\":\"dashboard_action\",\"entity_id\":\"%s\"}",
            entity_id
        );
    }
    if (written < 0 || (size_t)written >= payload_len) {
        return C300X_UI_HOMEASSISTANT_PAYLOAD_TOO_LARGE;
    }
    return C300X_UI_HOMEASSISTANT_PAYLOAD_OK;
}

enum c300x_ui_homeassistant_payload_result c300x_ui_homeassistant_build_payload(
    const char *query,
    char *payload,
    size_t payload_len
)
{
    char domain[32];
    char service[32];
    char entities[128];
    char option[160];
    char revision[48];
    char entity_id[128];
    char revision_json[128];
    char *selected_entity_id;
    int written;

    query_param_value(query, "domain", domain, sizeof(domain));
    query_param_value(query, "service", service, sizeof(service));
    query_param_value(query, "option", option, sizeof(option));
    query_param_value(query, "revision", revision, sizeof(revision));
    if (!query_param_value(query, "entities", entities, sizeof(entities))) {
        query_param_value(query, "entity_id", entities, sizeof(entities));
    }

    if (domain[0] == '\0' && service[0] == '\0' && entities[0] == '\0') {
        if (revision[0] != '\0') {
            if (!json_string(revision, revision_json, sizeof(revision_json))) {
                return C300X_UI_HOMEASSISTANT_PAYLOAD_TOO_LARGE;
            }
            written = snprintf(
                payload,
                payload_len,
                "{\"type\":\"dashboard\",\"revision\":%s}",
                revision_json
            );
        } else {
            written = snprintf(payload, payload_len, "{\"type\":\"dashboard\"}");
        }
        if (written < 0 || (size_t)written >= payload_len) {
            return C300X_UI_HOMEASSISTANT_PAYLOAD_TOO_LARGE;
        }
        return C300X_UI_HOMEASSISTANT_PAYLOAD_OK;
    }

    if (strcmp(domain, C300X_DASHBOARD_DOMAIN) != 0 || strcmp(service, "toggle") != 0 || entities[0] == '\0') {
        return C300X_UI_HOMEASSISTANT_PAYLOAD_UNSUPPORTED;
    }

    snprintf(entity_id, sizeof(entity_id), "%s", entities);
    selected_entity_id = first_entity_id(entity_id);
    return build_dashboard_action_payload(selected_entity_id, option, payload, payload_len);
}
