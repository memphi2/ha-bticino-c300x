#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif
#include "announce_file.h"
#include "announce.h"
#include "device_detect.h"

#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef __arm__
#include <sys/syscall.h>
#define ANNOUNCE_STAT struct stat64
/* The raw syscall fills the kernel's layout: only with 32-bit time is it glibc's. */
_Static_assert(sizeof(struct stat64) == 104, "struct stat64 must match the kernel's stat64");
#define announce_fstat(fd, info) ((int)syscall(SYS_fstat64, (fd), (info)))
#else
#define ANNOUNCE_STAT struct stat
#define announce_fstat(fd, info) fstat((fd), (info))
#endif
#include <unistd.h>

const char *c300x_announce_path(const char *name, const char *fallback)
{
    const char *value = getenv(name);
    return value != NULL && value[0] != '\0' ? value : fallback;
}

const char *c300x_announce_file(void)
{
    return c300x_announce_path("C300X_ANNOUNCE_FILE", "/tmp/c300x-announce.wav");
}

/* A file of the agent: a regular file of its own user with a single name. */
static int own_file(int fd, ANNOUNCE_STAT *info)
{
    return announce_fstat(fd, info) == 0 && S_ISREG(info->st_mode) && info->st_uid == geteuid() && info->st_nlink == 1;
}

static uint64_t le(const unsigned char *bytes, int count)
{
    uint64_t value = 0;
    while (count-- > 0) {
        value = (value << 8) | bytes[count];
    }
    return value;
}

/* The sound device takes only 8 kHz, 16 bit; anything else would play at the
 * wrong speed or not at all. All sizes come from the file, so the arithmetic
 * is 64 bit and every chunk must end inside the file. */
int c300x_announce_file_duration_ms(const char *file)
{
    unsigned char head[512];
    ANNOUNCE_STAT info;
    uint64_t used, at = 12, channels = 0, file_size;
    int fd = open(file, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    ssize_t got;

    if (fd < 0) {
        return 0;
    }
    got = own_file(fd, &info) ? read(fd, head, sizeof(head)) : -1;
    (void)close(fd);
    used = got > 0 ? (uint64_t)got : 0;
    if (used < 12 || memcmp(head, "RIFF", 4) != 0 || memcmp(head + 8, "WAVE", 4) != 0) {
        return 0;
    }
    file_size = (uint64_t)info.st_size;
    while (at + 8 <= used) {
        uint64_t size = le(head + at + 4, 4);
        if (size > file_size - at - 8) {
            return 0;
        }
        if (memcmp(head + at, "fmt ", 4) == 0) {
            if (size < 16 || at + 24 > used || le(head + at + 8, 2) != 1 || le(head + at + 12, 4) != 8000
                || le(head + at + 22, 2) != 16) {
                return 0;
            }
            channels = le(head + at + 10, 2);
        } else if (memcmp(head + at, "data", 4) == 0) {
            if (channels < 1 || channels > 2 || size == 0) {
                return 0;
            }
            return (int)(size / (16 * channels)) + 1;
        }
        at += 8 + size + (size & 1);
    }
    return 0;
}

int c300x_announce_file_write(long offset,
    const unsigned char *data, size_t len, const char **error)
{
    ANNOUNCE_STAT info;
    int fd;
    int ok;

    *error = "invalid_audio";
    if (offset < 0 || len == 0 || len > C300X_ANNOUNCE_MAX_BYTES
        || (unsigned long)offset > C300X_ANNOUNCE_MAX_BYTES - len) {
        return 0;
    }
    *error = "write_failed";
    /* Nothing another user put at this name is followed or written to. */
    if (offset == 0) {
        (void)unlink(c300x_announce_file());
    }
    fd = open(c300x_announce_file(), O_WRONLY | O_NOFOLLOW | O_CLOEXEC | (offset == 0 ? O_CREAT | O_EXCL : O_APPEND), 0600);
    if (fd < 0) {
        return 0;
    }
    ok = own_file(fd, &info);
    if (ok && info.st_size != offset) {
        *error = "invalid_audio";
        ok = 0;
    }
    ok = ok && write(fd, data, len) == (ssize_t)len;
    return close(fd) == 0 && ok;
}

/* Plain base64 only: the shared decoder stops at some characters and would
 * store a cut piece. */
int c300x_announce_plain_base64(const char *text)
{
    size_t len = strlen(text), pad = 0;

    if (len == 0 || len % 4 != 0) {
        return 0;
    }
    while (pad < 2 && text[len - 1 - pad] == '=') {
        pad++;
    }
    return strspn(text, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/") == len - pad;
}

int c300x_announce_supported(const struct c300x_announce *announce)
{
    return c300x_device_model() == C300X_DEVICE_MODEL_C300X && announce->door_events
        && access(c300x_announce_path("C300X_AMIXER", "/usr/bin/amixer"), X_OK) == 0
        && access(c300x_announce_path("C300X_APLAY", "/usr/bin/aplay"), X_OK) == 0
        && access(c300x_announce_path("C300X_ZL_TOOL", "/bin/zl38005_ioctl-v2"), X_OK) == 0
        && access(c300x_announce_path("C300X_ZL_PLAY_CONFIG", "/home/bticino/microsemi/MEMO_AM_PLAY.cr"), R_OK) == 0;
}
