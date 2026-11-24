#include "../src/picture_source.h"
#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <linux/videodev2.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

enum fault { NONE, OPEN_FAIL, REGULAR, OTHER_MINOR, OTHER_DRIVER, OTHER_CAP_DRIVER,
    OUTPUT, QUERY_FAIL, BAD_TYPE, FLAGS, BAD_RANGE, BAD_STEP, READ_FAIL, OFF_GRID,
    LOST_OWNER, EXPIRED, WRITE_FAIL, NOT_CHANGED, READBACK_FAIL, READBACK_OTHER, LOST_AFTER_WRITE,
    EXPIRED_IN_READBACK, EXPIRED_AFTER_READBACK };
static enum fault fault;
/* stock: the mxc_v4l2 signature without descriptors; decoder: the bound I2C driver. */
static int opens, closes, queries, reads, writes, written, flags, owner, raw[3], stock, i2c_fail, dirs;
/* At this read: the media is no longer ours, or the deadline has passed. */
static int lose_at, expire_at;
/* tvp5150: s_ctrl queues the I2C write; it lands after the first read-back pass.
 * Contrast is read from the driver cache, so it matches at once. */
static int queued = -1, queued_i, queued_after;
static const char *decoder;
static long long now;
long long c300x_monotonic_ms(void) { return now; }
static int active(void *ctx) { return ctx == &owner && owner; }
static void reset(enum fault f)
{
    fault = f;
    opens = closes = queries = reads = writes = written = flags = 0;
    lose_at = expire_at = 0;
    owner = 1;
    now = 1000;
    raw[0] = 105; raw[1] = 134; raw[2] = 154;
    stock = i2c_fail = dirs = 0;
    queued = -1;
    decoder = NULL;
}

static void reset_stock(const char *bound)
{
    reset(NONE);
    stock = 1;
    decoder = bound;
    /* .82 (1.7.19, adv7180) at every session start: written 90, 134, 172 = 40, 50, 60 %. */
    raw[0] = bound && !strcmp(bound, "adv7180") ? 90 ^ 0x80 : 90;
    raw[1] = 134; raw[2] = 172;
}

static char dir_token;
static int listed;
DIR *__wrap_opendir(const char *name)
{
    static const char root[] = "/sys/bus/i2c/drivers/";
    assert(!strncmp(name, root, sizeof(root) - 1));
    ++dirs;
    listed = 0;
    if (!decoder || strcmp(name + sizeof(root) - 1, decoder)) { errno = ENOENT; return NULL; }
    return (DIR *)&dir_token;
}
struct dirent *__wrap_readdir(DIR *dir)
{
    static const char *const names[] = {".", "..", "bind", "module", "uevent", "unbind", "2-0020"};
    static struct dirent entry;
    assert(dir == (DIR *)&dir_token);
    if (listed == (int)(sizeof(names) / sizeof(names[0]))) return NULL;
    snprintf(entry.d_name, sizeof(entry.d_name), "%s", names[listed++]);
    return &entry;
}
int __wrap_closedir(DIR *dir) { assert(dir == (DIR *)&dir_token); return 0; }

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
        if (stock) {
            cap->version = 0x10b;
            cap->capabilities = 0x05000005;
            return 0;
        }
        cap->capabilities = V4L2_CAP_DEVICE_CAPS | V4L2_CAP_VIDEO_CAPTURE;
        cap->device_caps = fault == OUTPUT ? V4L2_CAP_VIDEO_OUTPUT : V4L2_CAP_VIDEO_CAPTURE;
        return 0;
    }
    if (cmd == VIDIOC_QUERYCTRL) {
        struct v4l2_queryctrl *q = arg;
        assert(q->id == V4L2_CID_BRIGHTNESS + (unsigned)queries++);
        if (stock) { errno = EINVAL; return -1; }
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
        if (queued >= 0 && reads > queued_after) { raw[queued_i] = queued; queued = -1; }
        if ((fault == READ_FAIL && reads == 3) || (fault == READBACK_FAIL && reads == 6)) return -1;
        c->value = raw[i] + (fault == OFF_GRID && i == 2);
        if (i2c_fail && reads == i2c_fail) c->value = -1;
        if (fault == READBACK_OTHER && reads == 4) c->value += 15;
        if (fault == LOST_AFTER_WRITE && reads == 4) owner = 0;
        if (reads == 3 && fault == LOST_OWNER) owner = 0;
        if (lose_at && reads == lose_at) owner = 0;
        if (expire_at && reads == expire_at) now += 751;
        if (reads == 3 && fault == EXPIRED) now += 751;
        if ((reads == 4 && fault == EXPIRED_IN_READBACK) || (reads == 6 && fault == EXPIRED_AFTER_READBACK))
            now += 751;
        return 0;
    }
    /* A second write only puts back the value read before the first. */
    assert(cmd == VIDIOC_S_CTRL && queries == 3 && (writes++ ? writes == 2 : reads == 3));
    assert((flags & O_ACCMODE) == O_RDWR);
    written = c->value;
    if (fault == WRITE_FAIL && writes == 1) return -1;
    if (fault == NONE && stock && writes == 1 && i != 1 && decoder && !strcmp(decoder, "tvp5150")) {
        queued = c->value; queued_i = (int)i; queued_after = reads + 3;
    } else if (fault != NOT_CHANGED)
        raw[i] = c->value ^ (stock && i == 0 && decoder && !strcmp(decoder, "adv7180") ? 0x80 : 0);
    return 0;
}

static int profile = PICTURE_PROFILE_C300X;
static enum picture_source_result run(enum picture_field field, int value, int *out)
{
    struct picture_command command = {field, value};
    return picture_source_execute(profile, &command, out, active, &owner);
}

/* C100X 1.5.8 stack_open.xml, algo 1: day and night raw values per ten-percent step. */
static const int day[3][11] = {
    {30, 49, 68, 87, 106, 125, 144, 163, 182, 201, 220},
    {80, 97, 115, 132, 150, 167, 185, 202, 220, 237, 255},
    {80, 97, 115, 132, 150, 167, 185, 202, 220, 237, 255},
};
static const int night[3][11] = {
    {30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180},
    {50, 57, 64, 71, 78, 85, 92, 99, 106, 113, 120},
    {80, 91, 102, 113, 124, 135, 146, 157, 168, 179, 190},
};

static int nearest_day(int i, int value)
{
    int best = 0;
    for (int k = 1; k <= 10; k++)
        if (abs(value - day[i][k]) < abs(value - day[i][best])) best = k;
    return best * 10;
}

/* The C100X: same mxc_v4l2 signature as a C300X HW rev 4, tvp5150 bound, the station at 50 %. */
static void reset_c100x(void)
{
    reset_stock("tvp5150");
    raw[0] = day[0][5]; raw[1] = day[1][5]; raw[2] = day[2][5];
}

static void c100x_cases(void)
{
    int out[3] = {0};
    profile = PICTURE_PROFILE_C100X;
    reset_c100x();
    assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_OK && out[0] == 50 && out[1] == 50 && out[2] == 50);
    assert(!writes && queries == 3);
    /* Writes use the day table, so HA's percent is the station's own day percent. */
    for (int i = 0; i < 3; i++) {
        for (int percent = 0; percent <= 100; percent += 10) {
            reset_c100x();
            assert(run(PICTURE_BRIGHTNESS + i, percent, out) == PICTURE_SOURCE_OK);
            assert(raw[i] == day[i][percent / 10] && out[i] == percent);
            assert(writes == (percent != 50) && closes == 1);
            queries = reads = 0;
            assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_OK && out[i] == percent);
        }
    }
    /* Night values (re-applied on dark luma) read as the nearest day step, clamped. */
    for (int i = 0; i < 3; i++) {
        for (int k = 0; k <= 10; k++) {
            reset_c100x();
            raw[i] = night[i][k];
            assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_OK && !writes);
            assert(out[i] == nearest_day(i, night[i][k]));
        }
    }
    reset_c100x();
    raw[1] = night[1][0]; /* 50, below the day range: clamps to 0 %. */
    assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_OK && out[1] == 0);
    /* Menu steps off the 10 % grid: nearest day step, a tie to the lower one. */
    reset_c100x();
    raw[0] = 100; raw[1] = 106; raw[2] = 254;
    assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_OK && out[0] == 40 && out[1] == 10 && out[2] == 100);
    /* Outside every vendor range, and contrast 0 (unwritten driver cache after boot): unavailable. */
    static const int outside[][2] = {{0, 29}, {0, 221}, {1, 0}, {1, 49}, {2, 79}};
    for (unsigned n = 0; n < sizeof(outside) / sizeof(outside[0]); n++) {
        reset_c100x();
        raw[outside[n][0]] = outside[n][1];
        assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_UNAVAILABLE && !writes);
    }
    /* A night value is overwritten with the day value of the requested percent. */
    reset_c100x();
    raw[0] = night[0][4];
    assert(run(PICTURE_BRIGHTNESS, 30, out) == PICTURE_SOURCE_OK && writes == 1 && raw[0] == day[0][3]);
    /* Verification stays exact: a value that only snaps to the request is not applied. */
    reset_c100x();
    raw[0] = day[0][4] + 1;
    fault = NOT_CHANGED;
    assert(run(PICTURE_BRIGHTNESS, 40, out) == PICTURE_SOURCE_NOT_APPLIED);
    assert(writes == 2 && written == day[0][4] + 1 && raw[0] == day[0][4] + 1);
    /* No profile: nothing is opened. */
    reset_c100x();
    profile = PICTURE_PROFILE_NONE;
    assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_UNAVAILABLE && !opens);
    profile = PICTURE_PROFILE_C300X;
}

int main(void)
{
    reset(NONE);
    assert(picture_source_supported("C300X", "1.7.19") == PICTURE_PROFILE_C300X && !dirs);
    assert(!picture_source_supported("C100X", "1.7.19") && !dirs);
    static const char *const decoders[] = {NULL, "adv7180", "tvp5150", "other"};
    for (int d = 0; d < 4; d++) {
        decoder = decoders[d];
        assert(picture_source_supported("C300X", "1.7.19") == PICTURE_PROFILE_C300X);
        assert(picture_source_supported("C300X", "2.0.2") == (d == 1 || d == 2 ? PICTURE_PROFILE_C300X : 0));
        assert(picture_source_supported("C300X", "3.0.6") == (d == 1 || d == 2 ? PICTURE_PROFILE_C300X : 0));
        /* C100X: only 1.5.8 with its tvp5150 bound; the C300X firmwares never. */
        assert(picture_source_supported("C100X", "1.5.8") == (d == 2 ? PICTURE_PROFILE_C100X : 0));
        assert(!picture_source_supported("C300X", "1.5.8") && !picture_source_supported("C100X", "1.5.9"));
        assert(!picture_source_supported("C100X", "3.0.6") && !picture_source_supported("C300X", "3.0.5"));
        assert(!picture_source_supported("C300X", NULL) && !picture_source_supported(NULL, "2.0.2"));
    }
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
    for (enum fault f = OPEN_FAIL; f <= LOST_AFTER_WRITE; f++) {
        reset(f);
        out[0] = out[1] = out[2] = -1;
        int attempted = f >= WRITE_FAIL;
        assert(run(PICTURE_BRIGHTNESS, 60, out) ==
               (attempted ? PICTURE_SOURCE_NOT_APPLIED : PICTURE_SOURCE_UNAVAILABLE));
        /* Not confirmed: the previous value goes back unless the media is no longer ours. */
        assert(raw[0] == (f == LOST_AFTER_WRITE ? 120 : 105));
        assert(writes == (attempted ? 2 - (f == LOST_AFTER_WRITE) : 0) && closes == (f != OPEN_FAIL));
        assert(out[0] == -1 && out[1] == -1 && out[2] == -1);
    }
    /* The deadline bounds the read-back, not the rollback of a media that is still ours. */
    reset(EXPIRED_IN_READBACK);
    out[0] = -1;
    assert(run(PICTURE_BRIGHTNESS, 60, out) == PICTURE_SOURCE_NOT_APPLIED);
    assert(raw[0] == 105 && writes == 2 && reads == 4 && closes == 1 && out[0] == -1);
    /* A read-back that matched is applied, even when the deadline passes right after it. */
    reset(EXPIRED_AFTER_READBACK);
    assert(run(PICTURE_BRIGHTNESS, 60, out) == PICTURE_SOURCE_OK);
    assert(raw[0] == 120 && writes == 1 && reads == 6 && closes == 1 && out[0] == 60);
    reset(NONE);
    raw[0] = 0; /* Idle .82 returned 0,134,128; do not map this to 0%. */
    raw[2] = 128;
    assert(run(PICTURE_BRIGHTNESS, 50, out) == PICTURE_SOURCE_UNAVAILABLE && !writes);
    reset(NONE);
    assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_OK && !dirs);
    /* adv7180: XOR (all firmwares); unbound or tvp5150 (2.0.2 and 3.0.6, HW rev 1/4): plain. */
    for (int bound = 1; bound >= -1; bound--) {
        const char *name = bound > 0 ? "adv7180" : bound ? "tvp5150" : NULL;
        reset_stock(name);
        assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_OK);
        assert(out[0] == 40 && out[1] == 50 && out[2] == 60 && queries == 3 && dirs == 1);
        for (int i = 0; i < 3; i++) {
            for (int percent = 0; percent <= 100; percent += 10) {
                reset_stock(name);
                assert(run(PICTURE_BRIGHTNESS + i, percent, out) == PICTURE_SOURCE_OK);
                int written = first[i] + step[i] * (percent / 10);
                assert(raw[i] == (written ^ (bound > 0 && !i ? 0x80 : 0)) && out[i] == percent);
                assert(writes == (percent != 40 + 10 * i) && closes == 1);
                queries = reads = 0;
                assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_OK && out[i] == percent);
            }
        }
    }
    for (int i = 0; i < 3; i++) {
        reset_stock("tvp5150");
        assert(run(PICTURE_BRIGHTNESS + i, 100, out) == PICTURE_SOURCE_OK);
        assert(out[i] == 100 && raw[i] == first[i] + 10 * step[i] && writes == 1 && reads == (i == 1 ? 6 : 9));
    }
    reset_stock("tvp5150");
    fault = NOT_CHANGED; /* A write that never lands: bounded retries, then put back. */
    assert(run(PICTURE_BRIGHTNESS, 100, out) == PICTURE_SOURCE_NOT_APPLIED);
    assert(raw[0] == 90 && writes == 2 && reads == 21);
    reset_stock("tvp5150");
    fault = NOT_CHANGED;
    lose_at = 12; /* No longer ours in the second retry: stop reading, no write back. */
    assert(run(PICTURE_BRIGHTNESS, 100, out) == PICTURE_SOURCE_NOT_APPLIED);
    assert(writes == 1 && written == 180 && reads == 12 && closes == 1);
    reset_stock("tvp5150");
    fault = NOT_CHANGED;
    expire_at = 12; /* Deadline passed in the second retry: stop reading, one write back. */
    assert(run(PICTURE_BRIGHTNESS, 100, out) == PICTURE_SOURCE_NOT_APPLIED);
    assert(writes == 2 && written == 90 && reads == 12 && closes == 1);
    reset_stock("adv7180");
    decoder = NULL; /* Unbound: the register 218 is taken as is, off the range, never snapped. */
    assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_UNAVAILABLE);
    reset_stock("tvp5150");
    raw[1] = 0; /* tvp5150 contrast is a driver cache that is 0 until the first write after boot. */
    assert(run(PICTURE_READ, 0, out) == PICTURE_SOURCE_UNAVAILABLE);
    for (int failed = 1; failed <= 6; failed++) {
        reset_stock("adv7180");
        i2c_fail = failed; /* The stock driver answers a failed I2C read with -1 and success. */
        out[0] = out[1] = out[2] = -1;
        enum picture_source_result r = run(failed <= 3 ? PICTURE_READ : PICTURE_BRIGHTNESS, 100, out);
        assert(r == (failed <= 3 ? PICTURE_SOURCE_UNAVAILABLE : PICTURE_SOURCE_NOT_APPLIED));
        assert(raw[0] == (90 ^ 0x80) && writes == (failed > 3) * 2);
        assert(out[0] == -1 && out[1] == -1 && out[2] == -1);
    }
    c100x_cases();
    return 0;
}
