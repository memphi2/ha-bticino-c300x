/* Production core, CLI and HTTP route; reboot/remount boundaries are intercepted. */
#define main unused_agent_main
#include "../src/main.c"
#undef main
#include "../src/http_audio_codec.h"
#include "../src/http_util.h"
#include <assert.h>

static int remounts, writes, reboots, recorded;

int __wrap_c300x_device_file_remount(const char *mode)
{
    assert(strcmp(mode, "rw") == 0 || strcmp(mode, "ro") == 0);
    remounts++;
    return 1;
}

int __real_c300x_device_file_write(const char *, const char *, size_t);
int __wrap_c300x_device_file_write(const char *path, const char *data, size_t len)
{
    writes++;
    return __real_c300x_device_file_write(path, data, len);
}

void c300x_http_send_json(int fd, int status, const char *reason, const char *body)
{
    (void)reason;
    assert(fd == 123);
    printf("%d\n%s", status, body);
}

void c300x_http_service_reboot(struct c300x_http_maintenance *owner, int fd,
    const struct c300x_config *config, c300x_schedule_command_fn schedule,
    c300x_reboot_reply_fn reply, void *context, void (*destroy)(void *))
{
    (void)owner; (void)config; (void)schedule;
    reboots++;
    reply(fd, 1, context);
    destroy(context);
}

static void record_write(void *context, const char *kind, const char *action)
{
    (void)context; (void)action;
    assert(strcmp(kind, "audio_codec") == 0);
    recorded++;
}

int main(int argc, char **argv)
{
    assert(argc == 4);
    int result = 0;
    if (strcmp(argv[1], "cli") == 0) {
        result = run_audio_codec_cli(argv[2]);
    } else if (strcmp(argv[1], "remove") == 0) {
        char error[C300X_MAX_ERROR_LEN] = "";
        int ok = c300x_audio_codec_remove_patches(error, sizeof(error));
        printf("{\"ok\":%s,\"error\":\"%s\"}\n", ok ? "true" : "false", error);
        result = ok ? 0 : 1;
    } else {
        assert(strcmp(argv[1], "http") == 0);
        struct c300x_config config = {.api_no_auth = 1, .maintenance_enabled = 1,
            .maintenance_no_auth_allowed = 1, .maintenance_reboot_enabled = 1};
        struct c300x_http_maintenance owner = {.record_write = record_write};
        struct request request = {0};
        char body[128];
        if (strcmp(argv[2], "status") == 0) {
            strcpy(request.method, "GET");
            strcpy(request.path, "/api/v1/maintenance/audio-codec");
        } else {
            strcpy(request.method, "POST");
            snprintf(request.path, sizeof(request.path), "/api/v1/maintenance/audio-codec/actions/%s", argv[2]);
        }
        snprintf(body, sizeof(body), "{\"confirm\":\"%s_audio_codec_patch\",\"reboot\":true}", argv[2]);
        strcpy(request.body, body);
        assert(c300x_http_audio_codec_route(&owner, 123, &config, argv[3], &request, NULL));
    }
    fprintf(stderr, "{\"remounts\":%d,\"writes\":%d,\"reboots\":%d,\"recorded\":%d}\n",
        remounts, writes, reboots, recorded);
    return result;
}
