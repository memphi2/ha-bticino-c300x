#include "http_auth.h"
#include "json_util.h"
#include "string_util.h"
#include <string.h>
#include <strings.h>

int header_value(const struct request *request, const char *name, char *out, size_t out_len)
{
    const char *line = request->headers;
    const size_t name_len = strlen(name);

    if (out_len > 0) {
        out[0] = '\0';
    }
    while (*line != '\0') {
        const char *line_end = strstr(line, "\r\n");
        const char *value;
        size_t value_len;

        if (line_end == NULL) {
            line_end = line + strlen(line);
        }
        if ((size_t)(line_end - line) > name_len && strncasecmp(line, name, name_len) == 0 && line[name_len] == ':') {
            value = line + name_len + 1;
            while (value < line_end && (*value == ' ' || *value == '\t')) {
                value++;
            }
            value_len = (size_t)(line_end - value);
            while (value_len > 0 && (value[value_len - 1] == ' ' || value[value_len - 1] == '\t')) {
                value_len--;
            }
            if (value_len >= out_len) {
                value_len = out_len > 0 ? out_len - 1 : 0;
            }
            if (out_len > 0) {
                memcpy(out, value, value_len);
                out[value_len] = '\0';
            }
            return 1;
        }
        if (*line_end == '\0') {
            break;
        }
        line = line_end + 2;
    }
    return 0;
}

static int has_valid_bearer(const struct request *request, const char *token)
{
    const char *line = request->headers;
    const size_t prefix_len = strlen("authorization:");

    if (token == NULL || token[0] == '\0') {
        return 0;
    }
    while (*line != '\0') {
        const char *line_end = strstr(line, "\r\n");
        const char *value;
        const char *token_start;
        size_t token_len;

        if (line_end == NULL) {
            line_end = line + strlen(line);
        }
        if ((size_t)(line_end - line) > prefix_len && strncasecmp(line, "authorization:", prefix_len) == 0) {
            value = line + prefix_len;
            while (value < line_end && (*value == ' ' || *value == '\t')) {
                value++;
            }
            if ((size_t)(line_end - value) < 7 || strncasecmp(value, "Bearer ", 7) != 0) {
                return 0;
            }
            token_start = value + 7;
            while (token_start < line_end && (*token_start == ' ' || *token_start == '\t')) {
                token_start++;
            }
            token_len = (size_t)(line_end - token_start);
            while (token_len > 0 && (token_start[token_len - 1] == ' ' || token_start[token_len - 1] == '\t')) {
                token_len--;
            }
            return constant_time_equal(token_start, token_len, token);
        }
        if (*line_end == '\0') {
            break;
        }
        line = line_end + 2;
    }
    return 0;
}

int api_request_authorized(const struct c300x_config *config, const struct request *request)
{
    return config->api_no_auth || has_valid_bearer(request, config->api_token);
}

static int has_valid_maintenance_token(const struct c300x_config *config, const struct request *request)
{
    char supplied[C300X_MAX_TOKEN_LEN];

    if (config->maintenance_admin_token[0] == '\0') {
        return 0;
    }
    if (!header_value(request, "x-bticino-c300x-maintenance-token", supplied, sizeof(supplied))) {
        return 0;
    }
    return constant_time_equal(
        supplied,
        strlen(supplied),
        config->maintenance_admin_token
    );
}

int maintenance_authorized(const struct c300x_config *config, const struct request *request)
{
    return config->maintenance_enabled
        && ((config->api_no_auth && config->maintenance_no_auth_allowed)
            || has_valid_maintenance_token(config, request));
}

int maintenance_auth_available(const struct c300x_config *config)
{
    return config->maintenance_enabled
        && (
            config->maintenance_admin_token[0] != '\0'
            || (config->api_no_auth && config->maintenance_no_auth_allowed)
        );
}

int config_admin_authorized(const struct c300x_config *config, const struct request *request)
{
    /* The configured admin may re-enable maintenance, but API access cannot. */
    return has_valid_maintenance_token(config, request)
        || (config->api_no_auth && maintenance_authorized(config, request));
}

int auth_config_read_authorized(const struct c300x_config *config, const struct request *request)
{
    return config->api_no_auth || has_valid_bearer(request, config->api_token)
        || config_admin_authorized(config, request);
}

int confirm_matches(const struct request *request, const char *expected)
{
    char confirm[32];
    c300x_json_string_field(request->body, "confirm", confirm, sizeof(confirm));
    return strcmp(confirm, expected) == 0;
}
