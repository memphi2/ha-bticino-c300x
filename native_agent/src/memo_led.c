#include "memo_led.h"
#include "memo_store.h"
#include "json_util.h"
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/inotify.h>
#include <unistd.h>

static int attribute(char *path, size_t size, const char *name)
{
    const char *root = getenv("C300X_LED_CLASS_ROOT");
    int n = snprintf(path, size, "%s/led_memo/%s", root ? root : "/sys/class/leds", name);
    return n >= 0 && (size_t)n < size;
}

int c300x_memo_led_present(void)
{
    char path[PATH_MAX];
    return attribute(path, sizeof(path), "brightness") && access(path, F_OK) == 0;
}

int c300x_memo_led_watch(void)
{
    char path[PATH_MAX];
    if (!attribute(path, sizeof(path), "brightness")) return -1;
    int fd = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
    if (fd >= 0 && inotify_add_watch(fd, path, IN_MODIFY) < 0) {
        close(fd);
        return -1;
    }
    if (fd >= 0 && attribute(path, sizeof(path), "trigger"))
        (void)inotify_add_watch(fd, path, IN_MODIFY);
    return fd;
}

static int level(const char *path)
{
    FILE *f = fopen(path, "r");
    int n;
    char extra;
    if (!f) return -1;
    int ok = fscanf(f, "%d %c", &n, &extra) == 1 && n >= 0;
    fclose(f);
    return ok ? n : -1;
}

static int set_level(int on)
{
    char brightness[PATH_MAX], path[PATH_MAX], token[128], value[32];
    if (!attribute(brightness, sizeof(brightness), "brightness")) return 0;
    int current = level(brightness);
    if (current < 0) return 0;
    if ((current != 0) == on) return 1;
    if (!attribute(path, sizeof(path), "max_brightness")) return 0;
    int max = level(path);
    if (max <= 0 || !attribute(path, sizeof(path), "trigger")) return 0;
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    int manual = 0;
    while (fscanf(f, "%127s", token) == 1) {
        if (token[0] == '[') {
            manual = strcmp(token, "[none]") == 0;
            break;
        }
    }
    fclose(f);
    if (!manual) return 0;
    int len = snprintf(value, sizeof(value), "%d\n", on ? max : 0);
    int fd = open(brightness, O_WRONLY | O_TRUNC | O_CLOEXEC);
    if (fd < 0) return 0;
    int ok = write(fd, value, (size_t)len) == len;
    close(fd);
    return ok;
}

void c300x_memo_led_update(struct c300x_memo_led *led, int unread)
{
    if (unread) {
        led->claimed = 1;
        led->release_pending = 0;
        (void)set_level(1);
    } else if (led->claimed || led->release_pending) {
        led->claimed = 0;
        int text = c300x_native_memo_unread(led->text_root);
        int voice = c300x_native_memo_unread(led->voice_root);
        int on = text == 1 || voice == 1;
        led->release_pending = (!on && (text < 0 || voice < 0)) || !set_level(on);
    }
}

int c300x_memo_led_event(struct c300x_memo_led *led, const char *topic, const char *body)
{
    const char *value;
    int unread;
    if (!c300x_json_find_member(body, body + strlen(body), "unread", &value)) return 1;
    if ((strcmp(topic, "display_bridge.state") && strcmp(topic, "notifications"))
        || !c300x_json_object_valid(body) || !c300x_json_bool_field(body, "unread", &unread))
        return 0;
    c300x_memo_led_update(led, unread);
    return 1;
}
