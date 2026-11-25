/* Redacted issue #51 observations: pure parsing/transformation, no device I/O. */
#include "../../native_agent/src/device_user.c"
#include "../../native_agent/src/ringer_protocol.h"
#include <assert.h>

int main(void)
{
    int muted = -1, volume = -1, changed = 0;
    char error[128] = "";
    assert(c300x_ringer_muted_from_reply("*#8**33*1##", &muted));
    assert(muted == 0);
    assert(c300x_ringer_volume_from_reply("*#8**41*100##", &volume));
    assert(volume == 10);
    assert(!c300x_ringer_muted_from_reply("*#*1##", &muted));
    assert(!c300x_ringer_volume_from_reply("*#*1##", &volume));

    const char *reported =
        "<sip:alluser@plant.example> <sip:app1@plant.example>, <sip:app2@plant.example>, <sip:companion@plant.example>\n"
        "<sip:app1@plant.example> <sip:vdesip.bs.iotleg.com;transport=tls>\n"
        "<sip:app2@plant.example> <sip:vdesip.bs.iotleg.com;transport=tls>\n";
    const char *expected =
        "<sip:alluser@plant.example> <sip:app1@plant.example>, <sip:app2@plant.example>, <sip:companion@plant.example>, <sip:homeassistant@plant.example>\n"
        "<sip:app1@plant.example> <sip:vdesip.bs.iotleg.com;transport=tls>\n"
        "<sip:app2@plant.example> <sip:vdesip.bs.iotleg.com;transport=tls>\n";
    struct file_buffer route = {0};
    route.data = strdup(reported);
    assert(route.data);
    route.len = strlen(reported);
    assert(ensure_route_target(&route, "plant.example", "homeassistant@plant.example", &changed, error, sizeof(error)));
    assert(changed && strcmp(route.data, expected) == 0);
    changed = 0;
    assert(ensure_route_target(&route, "plant.example", "homeassistant@plant.example", &changed, error, sizeof(error)));
    assert(!changed && strcmp(route.data, expected) == 0);
    assert(remove_route_target(&route, &changed, error, sizeof(error)));
    assert(changed && strcmp(route.data, reported) == 0);
    free(route.data);
    return 0;
}
