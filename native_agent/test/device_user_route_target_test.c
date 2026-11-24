/* Removing the HA target from a route file, without touching the device. */
#include "../src/device_user.c"
#include <assert.h>

static void check(const char *input, const char *expected, int expect_changed)
{
    struct file_buffer route = {0};
    char error[128] = "";
    int changed = 0;
    route.len = strlen(input);
    route.data = malloc(route.len + 1);
    assert(route.data != NULL);
    memcpy(route.data, input, route.len + 1);
    int ok = remove_route_target(&route, &changed, error, sizeof(error));
    if (!ok || strcmp(route.data, expected) != 0 || route.len != strlen(expected)) {
        fprintf(stderr, "input [%s]: ok=%d error=%s output [%s]\n", input, ok, error, route.data);
        assert(0);
    }
    assert(changed == expect_changed);
    free(route.data);
}

int main(void)
{
    /* A last line without a newline that keeps an HA mention it cannot parse. */
    check("<sip:alluser@d.local> <sip:app@d.local>, <sip:homeassistant-1@d.local",
          "<sip:alluser@d.local> <sip:app@d.local>, <sip:homeassistant-1@d.local", 0);
    check("<sip:alluser@d.local> <sip:homeassistant-x>",
          "<sip:alluser@d.local> <sip:homeassistant-x>", 0);
    /* Parsable targets go, with and without a final newline. */
    check("<sip:alluser@d.local> <sip:app@d.local>, <sip:homeassistant-1@d.local>",
          "<sip:alluser@d.local> <sip:app@d.local>", 1);
    check("<sip:alluser@d.local> <sip:app@d.local>, <sip:homeassistant-1@d.local>\n",
          "<sip:alluser@d.local> <sip:app@d.local>\n", 1);
    check("<sip:alluser@d.local> <sip:homeassistant@d.local>\r\n<sip:b@d.local> <sip:app@d.local>",
          "<sip:b@d.local> <sip:app@d.local>", 1);
    check("<sip:alluser@d.local> <sip:app@d.local>\n", "<sip:alluser@d.local> <sip:app@d.local>\n", 0);
    return 0;
}
