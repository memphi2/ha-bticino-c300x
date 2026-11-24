/* Link-time substitutes only in the host HTTP integration test. */
#include "../src/picture_source.h"
#include "../src/video_rtsp.h"
#include <stdio.h>
#include <string.h>
#include <unistd.h>

void __wrap_resolve_device_firmware(const struct c300x_config *config, char *out, size_t size)
{
    snprintf(out, size, "%s", config ? config->device_firmware :
        (access("other-firmware", F_OK) == 0 ? "9.9.9" : "1.7.19"));
}

void __wrap_c300x_video_status(struct c300x_video *video, struct c300x_video_status *s)
{
    memset(s, 0, sizeof(*s));
    if (!video) return;
    FILE *f = fopen("session", "r");
    if (!f) return;
    char kind[16] = "";
    int valid = fscanf(f, "%15s %lu", kind, &s->picture_session) == 2;
    fclose(f);
    if (!valid) return;
    s->running = s->enabled = s->bridge_running = 1;
    s->ring_call_active = s->ring_media_active = !strcmp(kind, "ring");
    s->home_call_active = !strcmp(kind, "home");
    s->external_media_active = !strcmp(kind, "external");
    s->bridge_media_active = strcmp(kind, "idle") != 0;
    snprintf(s->media_owner, sizeof(s->media_owner), "%s", kind);
}

enum picture_source_result __wrap_picture_source_execute(const struct picture_command *command,
    int values[3], int (*active)(void *), void *ctx)
{
    FILE *f = fopen("source-calls", "a");
    if (!f) return PICTURE_SOURCE_UNAVAILABLE;
    fprintf(f, "%s\n", picture_name(command->field));
    fclose(f);
    for (int i = 0; !access("hold", F_OK) && i < 2000; i++) usleep(1000);
    if (!active(ctx) || !access("unavailable", F_OK)) return PICTURE_SOURCE_UNAVAILABLE;
    if (!access("not-applied", F_OK)) return PICTURE_SOURCE_NOT_APPLIED;
    values[0] = 20; values[1] = 30; values[2] = 40;
    if (command->field != PICTURE_READ) values[command->field - PICTURE_BRIGHTNESS] = command->value;
    return PICTURE_SOURCE_OK;
}
