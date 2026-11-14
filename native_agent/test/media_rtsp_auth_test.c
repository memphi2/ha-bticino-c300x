#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../src/c300x_agent.h"
#include "../src/media_base64.h"
#include "../src/media_rtsp_auth.h"

int main(void) {
    struct c300x_config config = {0};
    const char *valid = "DESCRIBE rtsp://localhost/doorbell RTSP/1.0\r\n"
        "Authorization: Basic dXNlcjpwYXNz\r\n\r\n";
    assert(c300x_media_rtsp_authorized(&config, valid));
    assert(c300x_media_rtsp_authorized(&config, "OPTIONS * RTSP/1.0\r\n\r\n"));
    strcpy(config.video_rtsp_username, "user");
    assert(!c300x_media_rtsp_authorized(&config, valid));
    strcpy(config.video_rtsp_password, "pass");
    assert(c300x_media_rtsp_authorized(&config, valid));
    const char *bad[] = {
        "", "Authorization: Basic dXNlcjpwYXNz\r\n",
        "Authorization: Basic dXNlcjpiYWQ=\r\n\r\n",
        "Authorization: Basic dXNlcjpwYXNzAAAA\r\n\r\n",
        "Authorization: Basic dXNlcjpwYXNz;junk\r\n\r\n",
        "Authorization: Basic dXNlcjpwYXNz|junk\r\n\r\n",
        "Authorization: Basic dXNlcjpwYXNz=\r\n\r\n",
        "Authorization: Digest dXNlcjpwYXNz\r\n\r\n",
        "X-Authorization: Basic dXNlcjpwYXNz\r\n\r\n",
        "Authorization: Basic dXNlcjpwYXNz\r\nAuthorization: Basic dXNlcjpwYXNz\r\n\r\n",
        "Content-Length: 41\r\n\r\nAuthorization: Basic dXNlcjpwYXNz\r\n",
    };
    char request[2048];
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        snprintf(request, sizeof(request), "DESCRIBE * RTSP/1.0\r\n%s", bad[i]);
        assert(!c300x_media_rtsp_authorized(&config, request));
    }
    assert(c300x_media_rtsp_authorized(&config,
        "DESCRIBE * RTSP/1.0\r\naUtHoRiZaTiOn:\t bAsIc\t dXNlcjpwYXNz \t\r\n\r\n"));
    config.video_rtsp_username[0] = '\0';
    assert(!c300x_media_rtsp_authorized(&config, valid));
    memset(config.video_rtsp_username, 'u', sizeof(config.video_rtsp_username) - 1);
    memset(config.video_rtsp_password, 'p', sizeof(config.video_rtsp_password) - 1);
    char plain[512], encoded[685];
    snprintf(plain, sizeof(plain), "%s:%s", config.video_rtsp_username, config.video_rtsp_password);
    assert(c300x_media_base64_encode((unsigned char *)plain, strlen(plain), encoded, sizeof(encoded)));
    snprintf(request, sizeof(request), "DESCRIBE * RTSP/1.0\r\nAuthorization: Basic %s\r\n\r\n", encoded);
    assert(c300x_media_rtsp_authorized(&config, request));
    return 0;
}
