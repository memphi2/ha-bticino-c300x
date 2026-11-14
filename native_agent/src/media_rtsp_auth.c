#include "media_rtsp_auth.h"

#include "c300x_agent.h"
#include "media_base64.h"
#include "string_util.h"

#include <stdio.h>
#include <string.h>
#include <strings.h>

bool c300x_media_rtsp_authorized(const struct c300x_config *config, const char *request)
{
    char credentials[2 * C300X_MAX_TOKEN_LEN];
    char expected[((sizeof(credentials) + 2) / 3) * 4 + 1];
    const char *authorization = NULL;
    size_t authorization_len = 0;
    const char *line;

    if (config == NULL || request == NULL) {
        return false;
    }
    if (!config->video_rtsp_username[0] && !config->video_rtsp_password[0]) {
        return true;
    }
    /* Partial credentials must never silently disable authentication. */
    if (!config->video_rtsp_username[0] || !config->video_rtsp_password[0]
        || strchr(config->video_rtsp_username, ':') != NULL) {
        return false;
    }
    line = strstr(request, "\r\n");
    if (line == NULL) {
        return false;
    }
    line += 2;
    while (*line != '\0' && strncmp(line, "\r\n", 2) != 0) {
        const char *end = strstr(line, "\r\n");
        if (end == NULL) {
            return false;
        }
        const char *next = end + 2;
        if ((size_t)(end - line) >= 14 && strncasecmp(line, "Authorization:", 14) == 0) {
            if (authorization != NULL) {
                return false;
            }
            authorization = line + 14;
            while (authorization < end && (*authorization == ' ' || *authorization == '\t')) {
                authorization++;
            }
            while (end > authorization && (end[-1] == ' ' || end[-1] == '\t')) {
                end--;
            }
            authorization_len = (size_t)(end - authorization);
        }
        line = next;
    }
    if (strncmp(line, "\r\n", 2) != 0 || authorization == NULL || authorization_len < 6
        || strncasecmp(authorization, "Basic", 5) != 0
        || (authorization[5] != ' ' && authorization[5] != '\t')) {
        return false;
    }
    authorization += 5;
    authorization_len -= 5;
    while (authorization_len > 0 && (*authorization == ' ' || *authorization == '\t')) {
        authorization++;
        authorization_len--;
    }
    int len = snprintf(credentials, sizeof(credentials), "%s:%s",
        config->video_rtsp_username, config->video_rtsp_password);
    if (len < 0 || len >= (int)sizeof(credentials)
        || !c300x_media_base64_encode((const unsigned char *)credentials, (size_t)len,
                                    expected, sizeof(expected))) {
        return false;
    }
    /* Comparing canonical Base64 also rejects NULs, padding and trailing-data tricks. */
    return constant_time_equal(authorization, authorization_len, expected) != 0;
}
