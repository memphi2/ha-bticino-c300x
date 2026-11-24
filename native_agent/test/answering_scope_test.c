#include "../src/answering_scope.h"
#include "../src/device_detect.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static enum c300x_device_model model;
static int sent, status;
static char body[256];

enum c300x_device_model __wrap_c300x_device_model(void) { return model; }
void __wrap_c300x_http_send_json(int fd, int code, const char *reason, const char *text)
{
    assert(fd == 7 && reason != NULL);
    ++sent;
    status = code;
    snprintf(body, sizeof(body), "%s", text);
}

static int refused(const char *method, const char *path)
{
    struct request request;
    memset(&request, 0, sizeof(request));
    snprintf(request.method, sizeof(request.method), "%s", method);
    snprintf(request.path, sizeof(request.path), "%s", path);
    sent = status = 0;
    body[0] = '\0';
    int answered = c300x_answering_route_refused(7, &request);
    assert(answered == sent);
    return answered;
}

int main(void)
{
    static const char *const gated[][2] = {
        {"GET", "/api/v1/answering-machine"}, {"POST", "/api/v1/answering-machine"},
        {"GET", "/api/v1/answering-machine/messages"}, {"GET", "/api/v1/answering-machine/messages/m1/video"},
        {"POST", "/api/v1/answering-machine/messages/actions/delete"},
        {"GET", "/api/v1/memos/voice/memo_1/audio"}, {"POST", "/api/v1/memos/actions/delete"},
    };
    static const char *const open[][2] = {
        {"GET", "/api/v1/memos"}, {"POST", "/api/v1/memos/text/actions/create"},
        {"GET", "/api/v1/answering-machines"}, {"GET", "/ui/memos"}, {"GET", "/api/v1/ringer"},
    };
    for (int c100x = 0; c100x <= 1; c100x++) {
        model = c100x ? C300X_DEVICE_MODEL_C100X : C300X_DEVICE_MODEL_C300X;
        for (unsigned i = 0; i < sizeof(gated) / sizeof(gated[0]); i++) {
            assert(refused(gated[i][0], gated[i][1]) == c100x);
            if (c100x)
                assert(status == 409 && !strcmp(body, "{\"ok\":false,\"error\":\"answering_machine_unsupported_model\"}\n"));
        }
        for (unsigned i = 0; i < sizeof(open) / sizeof(open[0]); i++)
            assert(!refused(open[i][0], open[i][1]));
    }
    return 0;
}
