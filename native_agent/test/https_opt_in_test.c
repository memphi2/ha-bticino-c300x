#include <assert.h>
#include <dlfcn.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "../src/video_rtsp.h"

static unsigned library_loads;
static struct c300x_video_status media;

void *__wrap_dlopen(const char *name, int flags)
{
    (void)name;
    (void)flags;
    library_loads++;
    return NULL;
}

static void test_video_status(struct c300x_video *video, struct c300x_video_status *status)
{
    (void)video;
    *status = media;
}

static int test_access(const char *path, int mode)
{
    (void)path;
    (void)mode;
    return -1;
}

#define c300x_video_status(video, status) test_video_status(video, status)
#define access test_access
#include "../src/http.c"
#undef access
#undef c300x_video_status

static void read_response(int pair[2], const char *expected)
{
    char response[16384];
    close(pair[0]);
    ssize_t count = read(pair[1], response, sizeof(response) - 1);
    assert(count > 0);
    response[count] = '\0';
    if (strstr(response, expected) == NULL) {
        fprintf(stderr, "Expected %s, received %s\n", expected, response);
    }
    assert(strstr(response, expected) != NULL);
    close(pair[1]);
}

static void configure(
    struct c300x_config *config, struct agent_runtime *runtime,
    struct request *request, int enabled, const char *expected
)
{
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    snprintf(request->body, sizeof(request->body), "{\"httpsCallbacksEnabled\":%s}", enabled ? "true" : "false");
    handle_auth_config_post(pair[0], config, runtime, request);
    read_response(pair, expected);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    struct c300x_config config;
    struct c300x_config loaded;
    struct agent_runtime *runtime = calloc(1, sizeof(*runtime));
    struct request *request = calloc(1, sizeof(*request));
    assert(runtime != NULL && request != NULL);
    c300x_default_config(&config);
    assert(!config.https_callbacks_enabled);
    c300x_https_init(config.https_callbacks_enabled);
    assert(!c300x_https_available() && !c300x_https_enabled());
    snprintf(config.config_path, sizeof(config.config_path), "%s", argv[1]);
    strcpy(config.api_token, "test-api-token");
    strcpy(config.api_file_token, "test-api-token");
    strcpy(config.maintenance_admin_token, "test-maintenance-token");
    config.maintenance_enabled = 1;
    runtime->config = &config;

    configure(&config, runtime, request, 1, "403 Forbidden");
    assert(!config.https_callbacks_enabled && runtime->agent_write_count == 0);
    strcpy(request->headers, "X-Bticino-C300X-Maintenance-Token: test-maintenance-token\r\n");
    configure(&config, runtime, request, 0, "200 OK");
    assert(runtime->agent_write_count == 0);
    configure(&config, runtime, request, 1, "\"restart_required\":true");
    assert(config.https_callbacks_enabled);
    assert(runtime->agent_write_count == 1 && library_loads == 0);
    struct stat before, after;
    assert(stat(config.config_path, &before) == 0);
    configure(&config, runtime, request, 1, "200 OK");
    assert(stat(config.config_path, &after) == 0);
    assert(before.st_ino == after.st_ino && before.st_mtim.tv_sec == after.st_mtim.tv_sec
        && before.st_mtim.tv_nsec == after.st_mtim.tv_nsec);
    assert(runtime->agent_write_count == 1);
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    api_capabilities(pair[0], &config, runtime);
    read_response(pair, "\"https_callbacks_configured\":true");
    assert(!c300x_https_available() && !c300x_https_enabled() && library_loads == 0);

    /* A pending mode change is reversible before any process restart. */
    configure(&config, runtime, request, 0, "\"restart_required\":false");
    assert(!config.https_callbacks_enabled && runtime->agent_write_count == 2);
    char error[256];
    assert(c300x_load_config(config.config_path, &loaded, error, sizeof(error)));
    assert(!loaded.https_callbacks_enabled);

    const size_t busy_fields[] = {
        offsetof(struct c300x_video_status, call_active),
        offsetof(struct c300x_video_status, clients),
        offsetof(struct c300x_video_status, media_starting),
        offsetof(struct c300x_video_status, bridge_media_active),
        offsetof(struct c300x_video_status, bridge_stop_in_progress),
        offsetof(struct c300x_video_status, external_media_active),
        offsetof(struct c300x_video_status, ring_call_active),
        offsetof(struct c300x_video_status, ring_media_active),
        offsetof(struct c300x_video_status, ring_audio_active),
        offsetof(struct c300x_video_status, home_call_active),
        offsetof(struct c300x_video_status, home_call_running),
        offsetof(struct c300x_video_status, ring_answer_requested),
        offsetof(struct c300x_video_status, talkback_running)
    };
    strcpy(request->body, "{\"confirm\":\"restart_agent\",\"only_if_idle\":true}");
    for (size_t i = 0; i < sizeof(busy_fields) / sizeof(busy_fields[0]); i++) {
        memset(&media, 0, sizeof(media));
        *(int *)((char *)&media + busy_fields[i]) = 1;
        assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
        handle_restart_agent(pair[0], &config, runtime, request);
        read_response(pair, "media_session_active");
    }
    memset(&media, 0, sizeof(media));
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    handle_restart_agent(pair[0], &config, runtime, request);
    read_response(pair, "502 Bad Gateway"); /* No real init script is executed. */

    assert(library_loads == 0);
    long status;
    const char *failure;
    assert(!c300x_https_post("https://example.invalid/callback", "X-Test", "test", "{}",
        NULL, 0, 100, &status, &failure));
    assert(strcmp(failure, "https_unavailable") == 0 && library_loads == 0);
    c300x_https_init(1);
    assert(c300x_https_enabled() && library_loads == 1);
    assert(!c300x_https_available());
    assert(library_loads == 1);
    free(request);
    free(runtime);
    return 0;
}
