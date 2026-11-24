#include "http_origin.h"

#include <string.h>
#include <strings.h>

static int simple_body_type(const char *content_type)
{
    static const char *const simple[] = {"text/plain", "application/x-www-form-urlencoded", "multipart/form-data"};
    size_t len;

    while (*content_type == ' ' || *content_type == '\t') {
        content_type++;
    }
    len = strcspn(content_type, "; \t");
    for (size_t index = 0; index < sizeof(simple) / sizeof(simple[0]); index++) {
        if (len == strlen(simple[index]) && strncasecmp(content_type, simple[index], len) == 0) {
            return 1;
        }
    }
    return 0;
}

int c300x_http_cross_site_safe(const char *method, const char *origin, const char *host, const char *content_type)
{
    if (origin != NULL && origin[0] != '\0') {
        const char *rest = strncasecmp(origin, "http://", 7) == 0 ? origin + 7
            : strncasecmp(origin, "https://", 8) == 0 ? origin + 8 : NULL;
        if (rest == NULL || host == NULL || strcasecmp(rest, host) != 0) {
            return 0;
        }
    }
    if (strcmp(method, "GET") != 0 && strcmp(method, "HEAD") != 0
        && content_type != NULL && simple_body_type(content_type)) {
        return 0;
    }
    return 1;
}
