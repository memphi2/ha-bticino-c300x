#define _LARGEFILE64_SOURCE 1
#include "picture_source.h"
#include "time_util.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <unistd.h>

static const unsigned ids[3] = {V4L2_CID_BRIGHTNESS, V4L2_CID_CONTRAST, V4L2_CID_SATURATION};

/* raw[k] is what the vendor HAL writes to the V4L2 user control for k * 10 %.
 * Do not scale by QUERYCTRL's (possibly wider) driver range.
 * C300X stock stack_open.xml (1.7.19, 2.0.2, 3.0.6): min + delta * k; only the
 * grid is a stock value. C100X 1.5.8 stack_open.xml (algo 1): the day range,
 * trunc(min + p * (max - min) / 100). bt_av_media re-applies its night range
 * on dark luma, and the stock menu steps are not linear: a value within lo..hi
 * (day and night ranges together) reads as the nearest day step. */
static const struct grid { int raw[11], lo, hi; } grids[2][3] = {
    {{{30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180}, 1, 0},
     {{59, 74, 89, 104, 119, 134, 149, 164, 179, 194, 209}, 1, 0},
     {{64, 82, 100, 118, 136, 154, 172, 190, 208, 226, 244}, 1, 0}},
    {{{30, 49, 68, 87, 106, 125, 144, 163, 182, 201, 220}, 30, 220},
     {{80, 97, 115, 132, 150, 167, 185, 202, 220, 237, 255}, 50, 255},
     {{80, 97, 115, 132, 150, 167, 185, 202, 220, 237, 255}, 80, 255}},
};

/* A decoder counts only while its I2C driver has a client bound, such as 2-0020. */
static int decoder_bound(const char *driver)
{
    char path[64];
    snprintf(path, sizeof(path), "/sys/bus/i2c/drivers/%s", driver);
    DIR *dir = opendir(path);
    if (!dir) return 0;
    int found = 0;
    struct dirent *entry;
    unsigned bus, address;
    while (!found && (entry = readdir(dir)))
        found = sscanf(entry->d_name, "%u-%4x", &bus, &address) == 2;
    closedir(dir);
    return found;
}

int picture_source_supported(const char *model, const char *firmware)
{
    if (!model || !firmware) return PICTURE_PROFILE_NONE;
    /* C100X 1.5.8: the HW rev 4 capture path, tvp5150 only. */
    if (!strcmp(model, "C100X"))
        return !strcmp(firmware, "1.5.8") && decoder_bound("tvp5150") ? PICTURE_PROFILE_C100X : PICTURE_PROFILE_NONE;
    if (strcmp(model, "C300X")) return PICTURE_PROFILE_NONE;
    /* 1.7.19 has only the adv7180 driver. 2.0.2 and 3.0.6: adv7180 on HW rev 2/3,
     * tvp5150 (plain brightness) on rev 1/4. */
    if (!strcmp(firmware, "1.7.19")) return PICTURE_PROFILE_C300X;
    return (!strcmp(firmware, "2.0.2") || !strcmp(firmware, "3.0.6")) &&
           (decoder_bound("adv7180") || decoder_bound("tvp5150")) ? PICTURE_PROFILE_C300X : PICTURE_PROFILE_NONE;
}

static int capture_source(int fd)
{
#ifdef __arm__
    struct stat64 st;
    if (syscall(SYS_fstat64, fd, &st)) return 0;
#else
    struct stat st;
    if (fstat(fd, &st)) return 0;
#endif
    if (!S_ISCHR(st.st_mode) || major(st.st_rdev) != 81 || minor(st.st_rdev) != 0) return 0;
    char driver[256];
    static const char suffix[] = "/bus/platform/drivers/mxc_v4l2_capture";
    ssize_t n = readlink("/sys/dev/char/81:0/device/driver", driver, sizeof(driver));
    if (n < (ssize_t)(sizeof(suffix)-1) || n == (ssize_t)sizeof(driver) ||
        memcmp(driver + n - (sizeof(suffix)-1), suffix, sizeof(suffix)-1)) return 0;
    struct v4l2_capability cap = {0};
    if (ioctl(fd, VIDIOC_QUERYCAP, &cap)) return 0;
    unsigned caps = (cap.capabilities & V4L2_CAP_DEVICE_CAPS) ? cap.device_caps : cap.capabilities;
    if (memcmp(cap.driver, "mxc_v4l2", sizeof("mxc_v4l2")) ||
        !(caps & V4L2_CAP_VIDEO_CAPTURE)) return 0;
    /* This stock driver implements G/S_CTRL but not QUERYCTRL. */
    return cap.version == 0x10b && cap.capabilities == 0x05000005 &&
           cap.device_caps == 0 && !cap.card[0] && !cap.bus_info[0] ? 2 : 1;
}

static int descriptor(int fd, const struct grid *g, int i, int source)
{
    struct v4l2_queryctrl q = {.id = ids[i]};
    if (ioctl(fd, VIDIOC_QUERYCTRL, &q)) return source == 2 && errno == EINVAL;
    if (q.id != ids[i] ||
        q.type != V4L2_CTRL_TYPE_INTEGER || q.step <= 0 ||
        (q.flags & (V4L2_CTRL_FLAG_DISABLED | V4L2_CTRL_FLAG_INACTIVE | V4L2_CTRL_FLAG_GRABBED |
                    V4L2_CTRL_FLAG_WRITE_ONLY | V4L2_CTRL_FLAG_READ_ONLY))) return 0;
    for (int k = 0; k <= 10; k++)
        if (g->raw[k] < q.minimum || g->raw[k] > q.maximum || ((int64_t)g->raw[k] - q.minimum) % q.step) return 0;
    return 1;
}

/* flip: the stock adv7180 driver writes brightness XOR 0x80 but reads the register raw. */
static int read_percent(int fd, const struct grid *g, int i, int source, int flip, int *out, int *raw)
{
    struct v4l2_control c = {.id = ids[i]};
    if (ioctl(fd, VIDIOC_G_CTRL, &c) || c.id != ids[i]) return 0;
    /* The stock driver reports a failed I2C read as -1 with success. */
    if (source == 2 && (c.value < 0 || c.value > 255)) return 0;
    if (flip && i == 0) c.value ^= 0x80;
    int step = -1;
    for (int k = 0; step < 0 && k <= 10; k++)
        if (c.value == g->raw[k]) step = k;
    for (int k = 0; step < 0 && c.value >= g->lo && c.value <= g->hi && k <= 10; k++)
        if (k == 10 || abs(c.value - g->raw[k]) <= abs(c.value - g->raw[k + 1])) step = k;
    if (step < 0) return 0;
    *raw = c.value;
    *out = step * 10;
    return 1;
}

static int current(long long deadline, int (*active)(void *), void *ctx)
{
    return c300x_monotonic_ms() < deadline && active(ctx);
}

enum picture_source_result picture_source_execute(int profile, const struct picture_command *command,
    int values[3], int (*active)(void *), void *ctx)
{
    if (profile != PICTURE_PROFILE_C300X && profile != PICTURE_PROFILE_C100X) return PICTURE_SOURCE_UNAVAILABLE;
    const struct grid *grid = grids[profile - PICTURE_PROFILE_C300X];
    if (!command || !values || !active || command->field < PICTURE_READ ||
        command->field > PICTURE_SATURATION) return PICTURE_SOURCE_UNAVAILABLE;
    int set = command->field != PICTURE_READ;
    if (set && (command->value < 0 || command->value > 100 || command->value % 10))
        return PICTURE_SOURCE_UNAVAILABLE;
    long long deadline = c300x_monotonic_ms() + 750;
    if (!current(deadline, active, ctx)) return PICTURE_SOURCE_UNAVAILABLE;
    int fd = open("/dev/video0", (set ? O_RDWR : O_RDONLY) | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return PICTURE_SOURCE_UNAVAILABLE;
    enum picture_source_result result = PICTURE_SOURCE_UNAVAILABLE;
    int observed[3], raw[3];
    int source = current(deadline, active, ctx) ? capture_source(fd) : 0;
    if (!source) goto done;
    int flip = source == 2 && decoder_bound("adv7180");
    for (int i = 0; i < 3; i++) {
        if (!current(deadline, active, ctx) || !descriptor(fd, &grid[i], i, source) ||
            !current(deadline, active, ctx) || !read_percent(fd, &grid[i], i, source, flip, &observed[i], &raw[i]))
            goto done;
    }
    int index = command->field - PICTURE_BRIGHTNESS;
    int target = set ? grid[index].raw[command->value / 10] : 0;
    if (set && raw[index] != target) {
        int previous = raw[index];
        struct v4l2_control c = {.id = ids[index], .value = target};
        if (!current(deadline, active, ctx)) goto done;
        result = PICTURE_SOURCE_NOT_APPLIED;
        int confirmed = !ioctl(fd, VIDIOC_S_CTRL, &c);
        /* tvp5150 s_ctrl only queues the I2C write: give it up to 5 x 10 ms to land. */
        for (int retries = -1;; ) {
            for (int i = 0; confirmed && i < 3; i++)
                confirmed = current(deadline, active, ctx)
                    && read_percent(fd, &grid[i], i, source, flip, &observed[i], &raw[i]);
            if (!confirmed || raw[index] == target) break;
            if (retries < 0) retries = decoder_bound("tvp5150") ? 5 : 0;
            if (!retries--) break;
            nanosleep(&(struct timespec){.tv_nsec = 10000000}, NULL);
        }
        if (!confirmed || raw[index] != target) {
            /* Do not leave a value the caller is told was not applied: one
             * write back while the media is ours, even past the deadline. */
            c.value = previous;
            if (active(ctx)) (void)ioctl(fd, VIDIOC_S_CTRL, &c);
            goto done;
        }
    } else if (!current(deadline, active, ctx)) goto done;
    memcpy(values, observed, sizeof(observed));
    result = PICTURE_SOURCE_OK;
done:
    close(fd);
    return result;
}
