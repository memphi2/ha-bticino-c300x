#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#include "video_snapshot.h"
#include "http_util.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/fb.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <time.h>
#include <unistd.h>

#define SNAPSHOT_MAX_DIMENSION 4096U
#define SNAPSHOT_MAX_ROW (SNAPSHOT_MAX_DIMENSION * 4U)
#define SNAPSHOT_MAX_BODY (C300X_HTTP_OUTPUT_LIMIT - 512U)

static pthread_mutex_t capture_lock = PTHREAD_MUTEX_INITIALIZER;
static struct timespec last_attempt;
static int attempted;

#ifdef __arm__
#define SNAPSHOT_STAT struct stat64
#else
#define SNAPSHOT_STAT struct stat
#endif

static int snapshot_fstat(int fd, SNAPSHOT_STAT *info)
{
#ifdef __arm__
    return (int)syscall(SYS_fstat64, fd, info);
#else
    return fstat(fd, info);
#endif
}

static int snapshot_fstatat(int fd, const char *name, SNAPSHOT_STAT *info)
{
#ifdef __arm__
    return (int)syscall(SYS_fstatat64, fd, name, info, 0);
#else
    return fstatat(fd, name, info, 0);
#endif
}

static int numeric_name(const char *name)
{
    if (*name == '\0') return 0;
    for (; *name; name++) if (*name < '0' || *name > '9') return 0;
    return 1;
}

static int owner_active(int process_fd, dev_t device)
{
    char name[32];
    int fd = openat(process_fd, "comm", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    ssize_t length;
    DIR *directory;
    struct dirent *entry;
    int found = 0;
    unsigned int scanned = 0;
    if (fd < 0) return 0;
    length = read(fd, name, sizeof(name));
    close(fd);
    if (length != 12 || memcmp(name, "bt_av_media\n", 12) != 0) return 0;
    fd = openat(process_fd, "fd", O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return 0;
    directory = fdopendir(fd);
    if (directory == NULL) { close(fd); return 0; }
    while (scanned++ < 4096 && (entry = readdir(directory)) != NULL) {
        SNAPSHOT_STAT info;
        if (numeric_name(entry->d_name)
            && snapshot_fstatat(dirfd(directory), entry->d_name, &info) == 0
            && S_ISCHR(info.st_mode) && info.st_rdev == device) {
            found = 1;
            break;
        }
    }
    closedir(directory);
    return found;
}

static int find_owner(dev_t device)
{
    DIR *directory = opendir("/proc");
    struct dirent *entry;
    int owner = -1;
    unsigned int scanned = 0;
    if (directory == NULL) return -1;
    while (scanned++ < 4096 && (entry = readdir(directory)) != NULL) {
        int fd;
        if (!numeric_name(entry->d_name)) continue;
        fd = openat(dirfd(directory), entry->d_name,
                    O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
        if (fd < 0) continue;
        if (owner_active(fd, device)) { owner = fd; break; }
        close(fd);
    }
    closedir(directory);
    return owner;
}

static int byte_channel(const struct fb_bitfield *field)
{
    return field->length == 8 && field->msb_right == 0
        && field->offset <= 24 && field->offset % 8 == 0;
}

static int geometry_valid(const struct fb_fix_screeninfo *f,
                          const struct fb_var_screeninfo *v)
{
    uint64_t end;
    if (f->type != FB_TYPE_PACKED_PIXELS || f->visual != FB_VISUAL_TRUECOLOR
        || v->bits_per_pixel != 32 || v->nonstd || v->grayscale || v->rotate
        || (v->vmode & (FB_VMODE_INTERLACED | FB_VMODE_DOUBLE | FB_VMODE_YWRAP))
        || !v->xres || !v->yres || v->xres_virtual > SNAPSHOT_MAX_DIMENSION
        || v->yres_virtual > SNAPSHOT_MAX_DIMENSION
        || v->xres > v->xres_virtual || v->yres > v->yres_virtual
        || v->xoffset > v->xres_virtual - v->xres
        || v->yoffset > v->yres_virtual - v->yres
        || f->line_length < (uint64_t)v->xres_virtual * 4
        || f->line_length > SNAPSHOT_MAX_ROW
        || !byte_channel(&v->red) || !byte_channel(&v->green) || !byte_channel(&v->blue)
        || v->red.offset == v->green.offset || v->red.offset == v->blue.offset
        || v->green.offset == v->blue.offset) return 0;
    if (v->transp.length && (!byte_channel(&v->transp)
        || v->transp.offset == v->red.offset || v->transp.offset == v->green.offset
        || v->transp.offset == v->blue.offset)) return 0;
    end = (uint64_t)(v->yoffset + v->yres - 1) * f->line_length
        + (uint64_t)(v->xoffset + v->xres) * 4;
    return end <= f->smem_len && end <= INT32_MAX;
}

static void little32(unsigned char *p, uint32_t value)
{
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(value >> (i * 8));
}

static int read_row(int fd, unsigned char *row, size_t size, off_t offset)
{
    size_t done = 0;
    unsigned int interruptions = 0;
    while (done < size) {
        ssize_t n = pread(fd, row + done, size - done, offset + (off_t)done);
        if (n < 0 && errno == EINTR && interruptions++ < 8) continue;
        if (n <= 0) return 0;
        done += (size_t)n;
    }
    return 1;
}

static int copy_frame(int fd, int owner, dev_t device, unsigned char **data, size_t *size)
{
    struct fb_fix_screeninfo f = {0}, after_f = {0};
    struct fb_var_screeninfo v = {0}, after_v = {0};
    unsigned char *row = NULL, *bmp = NULL;
    uint32_t width, height, stride;
    size_t length;
    int ok = 0;
    if (ioctl(fd, FBIOGET_FSCREENINFO, &f) < 0
        || ioctl(fd, FBIOGET_VSCREENINFO, &v) < 0 || !geometry_valid(&f, &v)
        || !owner_active(owner, device)) return 0;
    width = v.xres < 512 ? v.xres : 512;
    height = (uint32_t)((uint64_t)v.yres * width / v.xres);
    if (height > 307) {
        height = 307;
        width = (uint32_t)((uint64_t)v.xres * height / v.yres);
    }
    if (!width) width = 1;
    if (!height) height = 1;
    stride = (width * 3 + 3) & ~3U;
    length = 54 + (size_t)stride * height;
    if (length > SNAPSHOT_MAX_BODY) return 0;
    row = malloc((size_t)v.xres * 4);
    bmp = calloc(1, length);
    if (row == NULL || bmp == NULL) goto done;
    bmp[0] = 'B'; bmp[1] = 'M';
    little32(bmp + 2, (uint32_t)length);
    little32(bmp + 10, 54); little32(bmp + 14, 40);
    little32(bmp + 18, width); little32(bmp + 22, height);
    bmp[26] = 1; bmp[28] = 24;
    little32(bmp + 34, stride * height);
    for (uint32_t y = 0; y < height; y++) {
        uint32_t source_y = (uint32_t)((uint64_t)y * v.yres / height);
        off_t offset = (off_t)((uint64_t)(v.yoffset + source_y) * f.line_length
                              + (uint64_t)v.xoffset * 4);
        unsigned char *output = bmp + 54 + (size_t)(height - y - 1) * stride;
        if (!read_row(fd, row, (size_t)v.xres * 4, offset)) goto done;
        for (uint32_t x = 0; x < width; x++) {
            size_t source = (size_t)((uint64_t)x * v.xres / width) * 4;
            uint32_t pixel = (uint32_t)row[source] | (uint32_t)row[source + 1] << 8
                | (uint32_t)row[source + 2] << 16 | (uint32_t)row[source + 3] << 24;
            output[x * 3] = (unsigned char)(pixel >> v.blue.offset);
            output[x * 3 + 1] = (unsigned char)(pixel >> v.green.offset);
            output[x * 3 + 2] = (unsigned char)(pixel >> v.red.offset);
        }
    }
    if (!owner_active(owner, device)
        || ioctl(fd, FBIOGET_FSCREENINFO, &after_f) < 0
        || ioctl(fd, FBIOGET_VSCREENINFO, &after_v) < 0
        || !geometry_valid(&after_f, &after_v)
        || memcmp(&f, &after_f, sizeof(f))) goto done;
    /* LCD page flips do not invalidate the page already copied. Only accept
       full-frame vertical flips; all other geometry and format stay fixed. */
    if (v.yoffset != after_v.yoffset) {
        if (v.yoffset % v.yres || after_v.yoffset % v.yres) goto done;
        after_v.yoffset = v.yoffset;
    }
    if (memcmp(&v, &after_v, sizeof(v))) goto done;
    *data = bmp; *size = length; bmp = NULL; ok = 1;
done:
    free(row); free(bmp);
    return ok;
}

enum c300x_snapshot_result c300x_video_snapshot(unsigned char **data, size_t *size)
{
    struct timespec now;
    SNAPSHOT_STAT info;
    int fd = -1, owner = -1;
    enum c300x_snapshot_result result = C300X_SNAPSHOT_UNAVAILABLE;
    *data = NULL; *size = 0;
    if (pthread_mutex_trylock(&capture_lock) != 0) return C300X_SNAPSHOT_THROTTLED;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) goto done;
    if (attempted && (now.tv_sec < last_attempt.tv_sec + 2
        || (now.tv_sec == last_attempt.tv_sec + 2 && now.tv_nsec < last_attempt.tv_nsec))) {
        result = C300X_SNAPSHOT_THROTTLED;
        goto done;
    }
    last_attempt = now; attempted = 1;
    fd = open("/dev/fb0", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0 || snapshot_fstat(fd, &info) != 0 || !S_ISCHR(info.st_mode)) goto done;
    owner = find_owner(info.st_rdev);
    if (owner >= 0 && copy_frame(fd, owner, info.st_rdev, data, size)) result = C300X_SNAPSHOT_OK;
done:
    if (owner >= 0) close(owner);
    if (fd >= 0) close(fd);
    pthread_mutex_unlock(&capture_lock);
    return result;
}
