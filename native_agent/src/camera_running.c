#include "camera_quality.h"

#include "c300x_agent.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static const char *env_or(const char *name, const char *fallback)
{
    const char *value = getenv(name);
    return (value != NULL && value[0] != '\0') ? value : fallback;
}

/* The values in the file when the device started. An agent that restarts
 * without the device finds them in a note that names the boot. */
int c300x_camera_running_values(const char *settings, int low, struct c300x_camera_values *out)
{
    char boot[64] = "", noted[64] = "", temp[C300X_MAX_PATH_LEN];
    const char *note = env_or("C300X_CAMERA_RUNNING_NOTE", "/tmp/c300x-camera-running");
    FILE *fp = fopen(env_or("C300X_BOOT_ID_FILE", "/proc/sys/kernel/random/boot_id"), "r");
    struct c300x_camera_values v = {0};

    if (fp != NULL) {
        if (fscanf(fp, "%63s", boot) != 1) {
            boot[0] = '\0';
        }
        fclose(fp);
    }
    if (boot[0] != '\0' && (fp = fopen(note, "r")) != NULL) {
        int matched = fscanf(fp, "%63s %d %d %d %d", noted, &v.bitrate_kbps, &v.fps, &v.width, &v.height) == 5
            && strcmp(noted, boot) == 0;
        fclose(fp);
        if (matched && v.bitrate_kbps > 0 && v.fps > 0 && v.width > 0 && v.height > 0) {
            *out = v;
            return 1;
        }
    }
    if (!c300x_camera_quality_read_values(settings, low, &v)) {
        return 0;
    }
    *out = v;
    /* A note cut short must not pass for the values the device runs. */
    if (boot[0] != '\0' && snprintf(temp, sizeof(temp), "%s.tmp", note) < (int)sizeof(temp)
        && (fp = fopen(temp, "w")) != NULL) {
        int ok = fprintf(fp, "%s %d %d %d %d\n", boot, v.bitrate_kbps, v.fps, v.width, v.height) > 0;
        ok = fclose(fp) == 0 && ok;
        if (!ok || rename(temp, note) != 0) {
            unlink(temp);
        }
    }
    return 1;
}
