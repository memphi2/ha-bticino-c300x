/* An empty private directory is the entire write-ahead claim. No file
 * contents, fsync, or writes outside verified volatile storage are needed. */
#ifdef __arm__
#define _LARGEFILE64_SOURCE 1
#endif
#include "memo_led_claim.h"
#include <errno.h>
#include <fcntl.h>
#include <linux/magic.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/vfs.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <unistd.h>

#define CLAIM "c300x-agent.memo-led.claim"
#define DIR_FLAGS (O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)

static int trusted_dir(int fd, int marker)
{
#ifdef __arm__
    struct stat64 st;
    if (syscall(SYS_fstat64, fd, &st) < 0) return 0;
#else
    struct stat st;
    if (fstat(fd, &st) < 0) return 0;
#endif
    if (marker && st.st_uid == geteuid()) {
        if ((st.st_mode & 07777) == 0700) return MEMO_ACTIVE;
        if ((st.st_mode & 07777) == 0500) return MEMO_RELEASING;
    }
    if (marker) return 0;
    return (st.st_uid == 0 || st.st_uid == geteuid())
        && (!(st.st_mode & 0022) || (st.st_mode & S_ISVTX));
}

int c300x_memo_claim_open(enum memo_claim_state *held)
{
    const char *override = getenv("C300X_MEMO_LED_RUNTIME_DIR");
    /* On the device /run is a firmware symlink to /var/volatile/run. */
    const char *roots[] = {"/run", "/var/volatile/run", "/tmp", "/var/volatile/tmp"};
    *held = MEMO_UNCLAIMED;
    for (size_t i = 0; i < (override ? 1 : sizeof(roots) / sizeof(*roots)); i++) {
        int dir = open(override ? override : roots[i], DIR_FLAGS);
        if (dir < 0) continue;
        struct statfs fs;
        if (fstatfs(dir, &fs) == 0 && fs.f_type == TMPFS_MAGIC && trusted_dir(dir, 0)
            && faccessat(dir, ".", W_OK | X_OK, 0) == 0) {
            int marker = openat(dir, CLAIM, DIR_FLAGS);
            if (marker < 0 && errno == ENOENT) return dir;
            if (marker >= 0) {
                *held = trusted_dir(marker, 1);
                close(marker);
                if (*held) return dir;
            }
            close(dir);
            return -1; /* Never adopt, remove or bypass an untrusted marker. */
        }
        close(dir);
    }
    return -1;
}

int c300x_memo_claim_create(int dir)
{
    return dir >= 0 && mkdirat(dir, CLAIM, 0700) == 0;
}

int c300x_memo_claim_remove(int dir)
{
    return dir >= 0 && (unlinkat(dir, CLAIM, AT_REMOVEDIR) == 0 || errno == ENOENT);
}

/* The mode of the same private inode journals the ownership edge atomically. */
int c300x_memo_claim_pending(int dir, int pending)
{
    int fd = openat(dir, CLAIM, DIR_FLAGS);
    if (fd < 0) return 0;
    int ok = trusted_dir(fd, 1) && fchmod(fd, pending ? 0500 : 0700) == 0;
    close(fd);
    return ok;
}
