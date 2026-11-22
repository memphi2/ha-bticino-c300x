#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif
#define _POSIX_C_SOURCE 200809L

#include "camera_update_lock.h"

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <sys/file.h>
#include <sys/stat.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <unistd.h>

#ifdef __arm__
typedef struct stat64 lock_stat;
static int fd_stat(int fd, lock_stat *st) { return (int)syscall(SYS_fstat64, fd, st); }
#else
typedef struct stat lock_stat;
static int fd_stat(int fd, lock_stat *st) { return fstat(fd, st); }
#endif

int c300x_camera_update_lock_acquire(const char **error)
{
    const char *path = getenv("C300X_CAMERA_UPDATE_LOCK");
    lock_stat st;
    *error = "update_lock_invalid";
    if (!path || !*path) path = "/tmp/c300x-camera-quality.lock";
    int fd = open(path, O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    if (fd_stat(fd, &st) || !S_ISREG(st.st_mode) || st.st_nlink != 1
        || st.st_uid != geteuid() || (st.st_mode & 0077)) {
        close(fd);
        return -1;
    }
    if (flock(fd, LOCK_EX | LOCK_NB)) {
        if (errno == EWOULDBLOCK || errno == EAGAIN) *error = "update_busy";
        close(fd);
        return -1;
    }
    *error = "";
    return fd;
}
