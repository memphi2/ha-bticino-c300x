#include "../src/picture_source.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <linux/videodev2.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

enum fault { NONE, OPEN_FAIL, REGULAR, OTHER_MINOR, OTHER_DRIVER, OTHER_CAP_DRIVER,
    OUTPUT, QUERY_FAIL, BAD_TYPE, FLAGS, BAD_RANGE, BAD_STEP, READ_FAIL, OFF_GRID,
    LOST_OWNER, EXPIRED, WRITE_FAIL, NOT_CHANGED, READBACK_FAIL };
static enum fault fault;
static int opens, closes, queries, reads, writes, flags, owner, raw[3];
static long long now;
long long c300x_monotonic_ms(void) { return now; }
static int active(void *ctx) { return ctx == &owner && owner; }
static void reset(enum fault f)
{
    fault = f;
    opens = closes = queries = reads = writes = flags = 0;
    owner = 1;
    now = 1000;
    raw[0] = 105; raw[1] = 134; raw[2] = 154;
}

int __wrap_open(const char *name, int f, ...)
{
    assert(!strcmp(name, "/dev/video0"));
    flags = f;
    ++opens;
    return fault == OPEN_FAIL ? -1 : 77;
}
int __wrap_close(int fd) { assert(fd == 77); ++closes; return 0; }
int __wrap_fstat(int fd, struct stat *st)
{
    assert(fd == 77);
    *st = (struct stat){.st_mode = fault == REGULAR ? S_IFREG : S_IFCHR,
                        .st_rdev = makedev(81, fault == OTHER_MINOR)};
    return 0;
}
ssize_t __wrap_readlink(const char *name, char *buf, size_t len)
{
    assert(!strcmp(name, "/sys/dev/char/81:0/device/driver"));
    const char *target = fault == OTHER_DRIVER ? "/bus/usb/drivers/other"
        : "../../../bus/platform/drivers/mxc_v4l2_capture";
    assert(strlen(target) < len);
    memcpy(buf, target, strlen(target));
    return (ssize_t)strlen(target);
}
int __wrap_ioctl(int fd, unsigned long cmd, ...)
{
    assert(fd == 77);
    va_list ap;
    va_start(ap, cmd);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    if (cmd == VIDIOC_QUERYCAP) {
        struct v4l2_capability *cap = arg;
        strcpy((char *)cap->driver, fault == OTHER_CAP_DRIVER ? "other" : "mxc_v4l2");
        cap->capabilities = V4L2_CAP_DEVICE_CAPS | V4L2_CAP_VIDEO_CAPTURE;
        cap->device_caps = fault == OUTPUT ? V4L2_CAP_VIDEO_OUTPUT : V4L2_CAP_VIDEO_CAPTURE;
        return 0;
    }
    if (cmd == VIDIOC_QUERYCTRL) {
        struct v4l2_queryctrl *q = arg;
        assert(q->id == V4L2_CID_BRIGHTNESS + (unsigned)queries++);
        q->minimum = 0; q->maximum = 255; q->step = 1;
        q->type = V4L2_CTRL_TYPE_INTEGER;
        if (queries == 3) {
            if (fault == QUERY_FAIL) { errno = EINVAL; return -1; }
            if (fault == BAD_TYPE) q->type = V4L2_CTRL_TYPE_BOOLEAN;
            if (fault == FLAGS) q->flags = V4L2_CTRL_FLAG_READ_ONLY;
            if (fault == BAD_RANGE) q->maximum = 243;
            if (fault == BAD_STEP) q->step = 5;
        }
        return 0;
    }
    struct v4l2_control *c = arg;
    unsigned i = c->id - V4L2_CID_BRIGHTNESS;
    assert(i < 3);
    if (cmd == VIDIOC_G_CTRL) {
        assert(i == (unsigned)reads++ % 3);
        if ((fault == READ_FAIL && reads == 3) || (fault == READBACK_FAIL && reads == 6)) return -1;
        c->value = raw[i] + (fault == OFF_GRID && i == 2);
        if (reads == 3 && fault == LOST_OWNER) owner = 0;
        if (reads == 3 && fault == EXPIRED) now += 751;
        return 0;
    }
    assert(cmd == VIDIOC_S_CTRL && reads == 3 && queries == 3 && writes++ == 0);
    assert((flags & O_ACCMODE) == O_RDWR);
    if (fault == WRITE_FAIL) return -1;
    if (fault != NOT_CHANGED) raw[i] = c->value;
    return 0;
}

static enum picture_source_result run(enum picture_field field, int value, int *out)
{
    struct picture_command command = {field, value};
    return picture_source_execute(&command, out, active, &owner);
}

int main(void)
{
    assert(picture_source_supported("C300X", "1.7.19"));
    assert(!picture_source_supported("C100X", "1.7.19"));
    assert(!picture_source_supported("C300X", "2.0.2"));
    assert(!picture_source_supported("C300X", "3.0.6"));
    int out[3] = {0};
    reset(NONE);
    owner = 0;
    assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_UNAVAILABLE && !opens);
    owner = 1;
    assert(run(PICTURE_CONTRAST, 55, out) == PICTURE_SOURCE_UNAVAILABLE && !opens);
    assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_OK);
    assert(reads == 3 && !writes && closes == 1 && (flags & O_ACCMODE) == O_RDONLY);
    assert((flags & (O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)) == (O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC));
    assert(out[0] == 50 && out[1] == 50 && out[2] == 50);
    const int first[] = {30, 59, 64}, step[] = {15, 15, 18};
    for (int i = 0; i < 3; i++) {
        for (int percent = 0; percent <= 100; percent += 10) {
            reset(NONE);
            assert(run(PICTURE_BRIGHTNESS + i, percent, out) == PICTURE_SOURCE_OK);
            assert(raw[i] == first[i] + step[i] * (percent / 10) && out[i] == percent);
            assert(reads == (percent == 50 ? 3 : 6) && writes == (percent != 50) && closes == 1);
        }
    }
    for (enum fault f = OPEN_FAIL; f <= READBACK_FAIL; f++) {
        reset(f);
        out[0] = out[1] = out[2] = -1;
        int attempted = f >= WRITE_FAIL;
        assert(run(PICTURE_BRIGHTNESS, 60, out) ==
               (attempted ? PICTURE_SOURCE_NOT_APPLIED : PICTURE_SOURCE_UNAVAILABLE));
        assert(writes == attempted && closes == (f != OPEN_FAIL));
        assert(out[0] == -1 && out[1] == -1 && out[2] == -1);
    }
    reset(NONE);
    raw[0] = 0; /* Idle .82 returned 0,134,128; do not map this to 0%. */
    raw[2] = 128;
    assert(run(PICTURE_BRIGHTNESS, 50, out) == PICTURE_SOURCE_UNAVAILABLE && !writes);
    return 0;
}
