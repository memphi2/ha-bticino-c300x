#define _LARGEFILE64_SOURCE 1
#include "picture_source.h"
#include "time_util.h"

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
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

/* C300X 1.7.19 stock stack_open.xml: min + delta per ten-percent step.
 * The HAL passes this integer directly to the V4L2 user control. Do not
 * scale by QUERYCTRL's (possibly wider) driver range. */
static const struct { unsigned id; int min, delta; } controls[] = {
    {V4L2_CID_BRIGHTNESS, 30, 15}, {V4L2_CID_CONTRAST, 59, 15},
    {V4L2_CID_SATURATION, 64, 18}
};

int picture_source_supported(const char *model, const char *firmware)
{
    return model && firmware && !strcmp(model, "C300X") && !strcmp(firmware, "1.7.19");
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

static int descriptor(int fd, int i, int source)
{
    struct v4l2_queryctrl q = {.id = controls[i].id};
    if (ioctl(fd, VIDIOC_QUERYCTRL, &q)) return source == 2 && errno == EINVAL;
    if (q.id != controls[i].id ||
        q.type != V4L2_CTRL_TYPE_INTEGER || q.step <= 0 ||
        (q.flags & (V4L2_CTRL_FLAG_DISABLED | V4L2_CTRL_FLAG_INACTIVE | V4L2_CTRL_FLAG_GRABBED |
                    V4L2_CTRL_FLAG_WRITE_ONLY | V4L2_CTRL_FLAG_READ_ONLY))) return 0;
    int first = controls[i].min, delta = controls[i].delta;
    return first >= q.minimum && first + 10 * delta <= q.maximum &&
           ((int64_t)first - q.minimum) % q.step == 0 && delta % q.step == 0;
}

static int read_percent(int fd, int i, int source, int *out, int *raw)
{
    struct v4l2_control c = {.id = controls[i].id};
    if (ioctl(fd, VIDIOC_G_CTRL, &c) || c.id != controls[i].id) return 0;
    int64_t offset = (int64_t)c.value - controls[i].min;
    int delta = controls[i].delta;
    if (source == 2) {
        if (c.value < 0 || c.value > 255) return 0;
        /* The running capture may start outside the stock slider's travel.
         * Snap only its displayed position, never an untouched hardware value. */
        offset = offset < 0 ? 0 : offset > 10 * delta ? 10 * delta : offset;
        offset += delta / 2;
    } else if (offset < 0 || offset > 10 * delta || offset % delta) return 0;
    *raw = c.value;
    *out = (int)(offset / delta) * 10;
    return 1;
}

static int current(long long deadline, int (*active)(void *), void *ctx)
{
    return c300x_monotonic_ms() < deadline && active(ctx);
}

enum picture_source_result picture_source_execute(const struct picture_command *command,
    int values[3], int (*active)(void *), void *ctx)
{
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
    for (int i = 0; i < 3; i++) {
        if (!current(deadline, active, ctx) || !descriptor(fd, i, source) ||
            !current(deadline, active, ctx) || !read_percent(fd, i, source, &observed[i], &raw[i])) goto done;
    }
    int index = command->field - PICTURE_BRIGHTNESS;
    int target = set ? controls[index].min + controls[index].delta * (command->value / 10) : 0;
    if (set && raw[index] != target) {
        struct v4l2_control c = {.id = controls[index].id, .value = target};
        if (!current(deadline, active, ctx)) goto done;
        result = PICTURE_SOURCE_NOT_APPLIED;
        if (ioctl(fd, VIDIOC_S_CTRL, &c)) goto done;
        for (int i = 0; i < 3; i++)
            if (!current(deadline, active, ctx) || !read_percent(fd, i, source, &observed[i], &raw[i])) goto done;
        if (raw[index] != target) goto done;
    }
    if (!current(deadline, active, ctx)) goto done;
    memcpy(values, observed, sizeof(observed));
    result = PICTURE_SOURCE_OK;
done:
    close(fd);
    return result;
}
