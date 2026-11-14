#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/fb.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static struct fb_fix_screeninfo fixed;
static struct fb_var_screeninfo variable;
static int opens, owner_checks, rows, fail_read, fail_ioctl, change_geometry;
static int lose_owner, wrong_owner, wrong_device, short_reads, interrupt_reads;
static int fail_open, fail_stat, close_count;
static int pan_after_read, change_after_format, change_after_stride;
static uint32_t after_yoffset;
static int allocation_count, fail_allocation;
static long seconds;
static unsigned char frame[64];
static int proc_index, fd_index;

static int mock_open(const char *path, int flags, ...)
{
    assert(strcmp(path, "/dev/fb0") == 0);
    assert(flags == (O_RDONLY | O_CLOEXEC | O_NOFOLLOW));
    opens++;
    return fail_open ? -1 : 10;
}
static int mock_openat(int fd, const char *path, int flags, ...)
{
    assert((flags & (O_CLOEXEC | O_NOFOLLOW)) == (O_CLOEXEC | O_NOFOLLOW));
    assert((flags & O_ACCMODE) == O_RDONLY);
    if (fd == 20) { assert(strcmp(path, "680") == 0); return 21; }
    assert(fd == 21);
    if (strcmp(path, "comm") == 0) { owner_checks++; return 22; }
    assert(strcmp(path, "fd") == 0);
    fd_index = 0;
    return 23;
}
static DIR *mock_opendir(const char *path)
{
    assert(strcmp(path, "/proc") == 0);
    proc_index = 0;
    return (DIR *)(uintptr_t)20;
}
static DIR *mock_fdopendir(int fd) { assert(fd == 23); return (DIR *)(uintptr_t)23; }
static int mock_dirfd(DIR *d) { return (int)(uintptr_t)d; }
static int mock_closedir(DIR *d) { (void)d; return 0; }
static struct dirent *mock_readdir(DIR *d)
{
    static struct dirent entry;
    if ((uintptr_t)d == 20) {
        if (proc_index++) return NULL;
        strcpy(entry.d_name, "680");
    } else {
        assert((uintptr_t)d == 23);
        if (fd_index++) return NULL;
        strcpy(entry.d_name, "27");
    }
    return &entry;
}
static ssize_t mock_read(int fd, void *data, size_t size)
{
    assert(fd == 22 && size >= 12);
    memcpy(data, wrong_owner ? "other_media\n" : "bt_av_media\n", 12);
    return 12;
}
static int mock_fstat(int fd, struct stat *s)
{
    assert(fd == 10);
    memset(s, 0, sizeof(*s));
    s->st_mode = S_IFCHR;
    s->st_rdev = 29;
    return fail_stat ? -1 : 0;
}
static int mock_fstatat(int fd, const char *name, struct stat *s, int flags)
{
    assert(fd == 23 && strcmp(name, "27") == 0 && flags == 0);
    memset(s, 0, sizeof(*s));
    s->st_mode = S_IFCHR;
    s->st_rdev = wrong_device ? 30 : 29;
    return lose_owner && rows ? -1 : 0;
}
static int mock_close(int fd) { assert(fd >= 10); close_count++; return 0; }
static int mock_clock_gettime(clockid_t clock, struct timespec *t)
{
    assert(clock == CLOCK_MONOTONIC);
    t->tv_sec = seconds; t->tv_nsec = 0;
    return 0;
}
static void *mock_malloc(size_t size)
{
    assert(size <= 16384);
    if (++allocation_count == fail_allocation) return NULL;
    return malloc(size);
}
static void *mock_calloc(size_t count, size_t size)
{
    assert(count == 1 && size <= 471606);
    if (++allocation_count == fail_allocation) return NULL;
    return calloc(count, size);
}
static int mock_ioctl(int fd, unsigned long command, ...)
{
    va_list args;
    assert(fd == 10);
    if (fail_ioctl) return -1;
    va_start(args, command);
    void *output = va_arg(args, void *);
    if (command == FBIOGET_FSCREENINFO) {
        memcpy(output, &fixed, sizeof(fixed));
        if (change_after_stride && rows)
            ((struct fb_fix_screeninfo *)output)->line_length += 4;
    } else {
        assert(command == FBIOGET_VSCREENINFO);
        memcpy(output, &variable, sizeof(variable));
        if (change_geometry && rows) ((struct fb_var_screeninfo *)output)->yoffset++;
        if (pan_after_read && rows)
            ((struct fb_var_screeninfo *)output)->yoffset = after_yoffset;
        if (change_after_format && rows) {
            ((struct fb_var_screeninfo *)output)->red.offset = 0;
            ((struct fb_var_screeninfo *)output)->blue.offset = 16;
        }
    }
    va_end(args);
    return 0;
}
static ssize_t mock_pread(int fd, void *out, size_t size, off_t offset)
{
    assert(fd == 10 && size <= 16384 && offset >= 0);
    rows++;
    if (interrupt_reads) { interrupt_reads--; errno = EINTR; return -1; }
    if (fail_read) return fail_read == 1 ? 0 : -1;
    if (short_reads && size > 3) size = 3;
    for (size_t i = 0; i < size; i++) ((unsigned char *)out)[i] = frame[((size_t)offset + i) % sizeof(frame)];
    return (ssize_t)size;
}

#define open mock_open
#define openat mock_openat
#define opendir mock_opendir
#define fdopendir mock_fdopendir
#define dirfd mock_dirfd
#define closedir mock_closedir
#define readdir mock_readdir
#define read mock_read
#define pread mock_pread
#define fstat mock_fstat
#define fstatat mock_fstatat
#define close mock_close
#define clock_gettime mock_clock_gettime
#define ioctl mock_ioctl
#define malloc mock_malloc
#define calloc mock_calloc
#include "../src/video_snapshot.c"

static uint32_t get32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static void reset(void)
{
    memset(&fixed, 0, sizeof(fixed)); memset(&variable, 0, sizeof(variable));
    fixed.type = FB_TYPE_PACKED_PIXELS; fixed.visual = FB_VISUAL_TRUECOLOR;
    fixed.line_length = 16; fixed.smem_len = 64;
    variable.xres = 2; variable.yres = 2;
    variable.xres_virtual = 4; variable.yres_virtual = 4;
    variable.xoffset = 1; variable.yoffset = 1; variable.bits_per_pixel = 32;
    variable.red.offset = 16; variable.green.offset = 8; variable.blue.offset = 0;
    variable.red.length = variable.green.length = variable.blue.length = 8;
    for (unsigned int i = 0; i < sizeof(frame); i++) frame[i] = (unsigned char)i;
    opens = owner_checks = rows = fail_read = fail_ioctl = change_geometry = 0;
    lose_owner = wrong_owner = wrong_device = short_reads = interrupt_reads = 0;
    fail_open = fail_stat = close_count = attempted = 0;
    pan_after_read = change_after_format = change_after_stride = 0;
    after_yoffset = 0;
    allocation_count = fail_allocation = 0;
    seconds = 10;
}
static void unavailable(void)
{
    unsigned char *data = (unsigned char *)(uintptr_t)1;
    size_t size = 123;
    assert(c300x_video_snapshot(&data, &size) == C300X_SNAPSHOT_UNAVAILABLE);
    assert(data == NULL && size == 0);
    assert(c300x_video_snapshot(&data, &size) == C300X_SNAPSHOT_THROTTLED);
    assert(opens == 1);
}

static void device_framebuffer(void)
{
    reset();
    variable.xres = variable.xres_virtual = 800;
    variable.yres = 480; variable.yres_virtual = 1440;
    variable.xoffset = variable.yoffset = 0;
    fixed.line_length = 3200; fixed.smem_len = 4608000;
}

static void normal_page_flips(void)
{
    unsigned char *data;
    size_t size;
    /* The live C300X failed with identical metadata except yoffset 960 -> 480. */
    for (uint32_t before = 0; before < 3; before++) {
        for (uint32_t after = 0; after < 3; after++) {
            device_framebuffer();
            variable.yoffset = before * 480;
            pan_after_read = 1; after_yoffset = after * 480;
            assert(c300x_video_snapshot(&data, &size) == C300X_SNAPSHOT_OK);
            assert(size == 471606 && rows == 307);
            free(data);
        }
    }
    device_framebuffer(); pan_after_read = 1; after_yoffset = 1;
    unavailable();
    device_framebuffer(); variable.yoffset = 1; pan_after_read = 1; after_yoffset = 480;
    unavailable();
    device_framebuffer(); pan_after_read = 1; after_yoffset = 1440;
    unavailable();
    device_framebuffer(); pan_after_read = 1; after_yoffset = UINT32_MAX;
    unavailable();
    device_framebuffer(); pan_after_read = 1; after_yoffset = 480; change_after_format = 1;
    unavailable();
    device_framebuffer(); pan_after_read = 1; after_yoffset = 480; change_after_stride = 1;
    unavailable();
    device_framebuffer(); pan_after_read = 1; after_yoffset = 480; lose_owner = 1;
    unavailable();
}

int main(void)
{
    unsigned char *data;
    size_t size;
    reset();
    assert(c300x_video_snapshot(&data, &size) == C300X_SNAPSHOT_OK);
    assert(size == 70 && get32(data + 2) == size && get32(data + 10) == 54);
    assert(get32(data + 18) == 2 && get32(data + 22) == 2 && data[28] == 24);
    assert(data[54] == 36 && data[55] == 37 && data[56] == 38);
    assert(data[62] == 20 && data[63] == 21 && data[64] == 22);
    assert(data[60] == 0 && data[61] == 0 && owner_checks == 3);
    free(data);
    seconds = 11;
    assert(c300x_video_snapshot(&data, &size) == C300X_SNAPSHOT_THROTTLED);
    seconds = 12;
    assert(c300x_video_snapshot(&data, &size) == C300X_SNAPSHOT_OK); free(data);
    reset(); short_reads = 1; interrupt_reads = 1;
    variable.red.offset = 0; variable.blue.offset = 16;
    assert(c300x_video_snapshot(&data, &size) == C300X_SNAPSHOT_OK);
    assert(data[54] == 38 && data[56] == 36); free(data);
    reset(); fail_open = 1; unavailable();
    reset(); fail_stat = 1; unavailable();
    reset(); wrong_owner = 1; unavailable(); assert(rows == 0);
    reset(); wrong_device = 1; unavailable(); assert(rows == 0);
    reset(); lose_owner = 1; unavailable(); assert(rows > 0);
    reset(); change_geometry = 1; unavailable();
    reset(); fail_ioctl = 1; unavailable();
    reset(); fail_allocation = 1; unavailable();
    reset(); fail_allocation = 2; unavailable();
    reset(); fail_read = 1; unavailable();
    reset(); fail_read = 2; unavailable();
    reset(); interrupt_reads = 100; unavailable(); assert(rows == 9);
    reset(); variable.bits_per_pixel = 16; unavailable();
    reset(); variable.red.offset = 8; unavailable();
    reset(); variable.red.msb_right = 1; unavailable();
    reset(); variable.red.length = 10; unavailable();
    reset(); variable.transp.length = 8; variable.transp.offset = 16; unavailable();
    reset(); variable.xoffset = UINT32_MAX; unavailable();
    reset(); variable.yoffset = UINT32_MAX; unavailable();
    reset(); fixed.line_length = UINT32_MAX; unavailable();
    reset(); fixed.smem_len = 43; unavailable();
    reset(); fixed.visual = FB_VISUAL_DIRECTCOLOR; unavailable();
    reset(); fixed.type = FB_TYPE_PLANES; unavailable();
    reset(); variable.xres = 0; unavailable();
    reset(); variable.nonstd = 1; unavailable();
    reset(); variable.vmode = FB_VMODE_YWRAP; unavailable();
    reset(); variable.rotate = 1; unavailable();
    reset(); variable.grayscale = 1; unavailable();
    reset(); variable.xres = variable.xres_virtual = 800;
    variable.yres = 480; variable.yres_virtual = 1440;
    variable.xoffset = variable.yoffset = 0;
    fixed.line_length = 3200; fixed.smem_len = 4608000;
    assert(c300x_video_snapshot(&data, &size) == C300X_SNAPSHOT_OK);
    assert(get32(data + 18) == 512 && get32(data + 22) == 307);
    assert(size == 471606 && size + 256 < C300X_HTTP_OUTPUT_LIMIT);
    assert(rows == 307); free(data);
    reset(); variable.xres = variable.xres_virtual = 1;
    variable.yres = variable.yres_virtual = 4096;
    variable.xoffset = variable.yoffset = 0;
    fixed.line_length = 4; fixed.smem_len = 16384;
    assert(c300x_video_snapshot(&data, &size) == C300X_SNAPSHOT_OK);
    assert(size < SNAPSHOT_MAX_BODY && get32(data + 22) == 307); free(data);
    reset();
    assert(pthread_mutex_lock(&capture_lock) == 0);
    assert(c300x_video_snapshot(&data, &size) == C300X_SNAPSHOT_THROTTLED);
    assert(opens == 0 && data == NULL && size == 0);
    assert(pthread_mutex_unlock(&capture_lock) == 0);
    normal_page_flips();
    return 0;
}
