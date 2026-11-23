/* The loopback firmware fixture has real processes and sockets but no
 * privileged mounts. Expose its mount transition only in this test binary. */
#include <sys/statvfs.h>
#include <unistd.h>

int __real_statvfs(const char *, struct statvfs *);

int __wrap_statvfs(const char *path, struct statvfs *fs)
{
    int result = __real_statvfs(path, fs);
    if (!result && access("firmware-writable", F_OK) != 0) fs->f_flag |= ST_RDONLY;
    return result;
}
