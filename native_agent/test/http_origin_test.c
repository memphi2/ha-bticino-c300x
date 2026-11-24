/* Cross-site browser requests are refused, HA and the setup page are not. */
#include <assert.h>
#include <stddef.h>

#include "../src/http_origin.h"

int main(void)
{
    /* Home Assistant (aiohttp): no Origin, JSON bodies. */
    assert(c300x_http_cross_site_safe("POST", "", "192.168.1.5:8091", "application/json"));
    assert(c300x_http_cross_site_safe("POST", NULL, "192.168.1.5:8091", NULL));
    assert(c300x_http_cross_site_safe("GET", NULL, "192.168.1.5:8091", NULL));
    /* The setup page served by the agent itself. */
    assert(c300x_http_cross_site_safe("POST", "http://192.168.1.5:8091", "192.168.1.5:8091", "application/json"));
    assert(c300x_http_cross_site_safe("POST", "HTTP://C300X.local:8091", "c300x.local:8091", "application/json"));
    /* A page of another site: refused whatever it sends. */
    assert(!c300x_http_cross_site_safe("POST", "http://evil.example", "192.168.1.5:8091", "application/json"));
    assert(!c300x_http_cross_site_safe("GET", "http://192.168.1.5:8092", "192.168.1.5:8091", NULL));
    assert(!c300x_http_cross_site_safe("POST", "null", "192.168.1.5:8091", NULL));
    assert(!c300x_http_cross_site_safe("POST", "http://192.168.1.5:8091", NULL, NULL));
    /* Bodies a form or no-cors fetch sends without a preflight. */
    assert(!c300x_http_cross_site_safe("POST", NULL, "192.168.1.5:8091", "text/plain;charset=UTF-8"));
    assert(!c300x_http_cross_site_safe("POST", NULL, "192.168.1.5:8091", " Application/X-WWW-Form-Urlencoded"));
    assert(!c300x_http_cross_site_safe("DELETE", NULL, "192.168.1.5:8091", "multipart/form-data; boundary=x"));
    assert(c300x_http_cross_site_safe("POST", NULL, "192.168.1.5:8091", "text/plainer"));
    return 0;
}
