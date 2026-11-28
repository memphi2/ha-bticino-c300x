#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#include "c100x_payload.h"

#include <sys/stat.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <unistd.h>

int c100x_payload_usable(const char *path)
{
#ifdef __arm__
    /* The device's glibc exports no lstat symbol. */
    struct stat64 info;
    int found = (int)syscall(SYS_lstat64, path, &info) == 0;
#else
    struct stat info;
    int found = lstat(path, &info) == 0;
#endif
    return found && S_ISREG(info.st_mode) && info.st_nlink == 1;
}
