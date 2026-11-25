#include "answering_scope.h"
#include "device_detect.h"
#include "http_util.h"

#include <string.h>

static int starts_with(const char *text, const char *prefix)
{
    return strncmp(text, prefix, strlen(prefix)) == 0;
}

int c300x_answering_route_refused(int client_fd, const struct request *request)
{
    const char *path = request->path;
    if (c300x_device_model() != C300X_DEVICE_MODEL_C100X) return 0;
    if (strcmp(path, "/api/v1/answering-machine") && !starts_with(path, "/api/v1/answering-machine/")
        && !starts_with(path, "/api/v1/memos/voice/") && strcmp(path, "/api/v1/memos/actions/delete"))
        return 0;
    c300x_http_send_json(client_fd, 409, "Conflict",
        "{\"ok\":false,\"error\":\"" C300X_ANSWERING_UNSUPPORTED_MODEL "\"}\n");
    return 1;
}
