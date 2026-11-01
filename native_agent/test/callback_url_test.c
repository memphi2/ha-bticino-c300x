#include "../src/http_util.h"

#include <assert.h>
#include <string.h>

int main(void)
{
    char host[256], port[16], path[256];
    const char *valid[][4] = {
        {"http://ha.example/callback", "ha.example", "80", "/callback"},
        {"http://192.0.2.10:8123/api/webhook/id", "192.0.2.10", "8123", "/api/webhook/id"},
        {"https://ha.example", "ha.example", "443", "/"},
        {"https://ha.example:8123/api/webhook/id", "ha.example", "8123", "/api/webhook/id"},
        {"https://[2001:db8::1]:8443/path", "2001:db8::1", "8443", "/path"},
        {"http://[2001:db8::1]/path", "2001:db8::1", "80", "/path"},
    };
    for (size_t i = 0; i < sizeof(valid) / sizeof(valid[0]); i++) {
        assert(parse_http_url(valid[i][0], host, sizeof(host), port, sizeof(port), path, sizeof(path)));
        assert(strcmp(host, valid[i][1]) == 0);
        assert(strcmp(port, valid[i][2]) == 0);
        assert(strcmp(path, valid[i][3]) == 0);
    }
    const char *invalid[] = {
        "ftp://ha.example/", "https:///path", "https://ha.example:0/",
        "https://ha.example:65536/", "https://ha.example:abc/",
        "https://ha.example:/", "https://user:password@ha.example/",
        "https://ha.example/path#fragment", "https://ha.example/\r\nHeader: injected",
        "https://[2001:db8::1/path", "https://ha.example?query", "https://ha.example/path with spaces",
    };
    for (size_t i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++) {
        assert(!parse_http_url(invalid[i], host, sizeof(host), port, sizeof(port), path, sizeof(path)));
    }
    assert(!parse_http_url("https://ha.example/long-path", host, sizeof(host), port, sizeof(port), path, 5));
    assert(!parse_http_url("https://ha.example", host, sizeof(host), port, 2, path, sizeof(path)));
    assert(!parse_http_url("https://ha.example", host, sizeof(host), port, sizeof(port), path, 1));
    return 0;
}
