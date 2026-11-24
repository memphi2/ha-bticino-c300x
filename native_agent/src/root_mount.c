#include "root_mount.h"

#include "pthread_compat.h"

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/statvfs.h>
#include <unistd.h>

static pthread_mutex_t root_lock = PTHREAD_MUTEX_INITIALIZER;
/* root_foreign: the open window found / writable by someone else.
 * root_was_writable: it found / writable at all, also left open by us. */
static int root_writers, root_foreign, root_was_writable, root_left_open;

static int root_mount_run(const char *mode)
{
    char command[64];
    if (snprintf(command, sizeof(command), "mount -o remount,%s / >/dev/null 2>&1", mode) >= (int)sizeof(command)) {
        return 0;
    }
    return system(command) == 0;
}

static int root_is_writable(void)
{
    struct statvfs root;
    return statvfs("/", &root) == 0 && (root.f_flag & ST_RDONLY) == 0;
}

/* A tmpfs mark, so a restarted agent (self-update, crash) still knows the
 * writable root is its own; a reboot mounts / read-only and drops it. */
static const char *mark_path(void)
{
    const char *path = getenv("C300X_ROOT_LEFT_OPEN_MARK");
    return path != NULL && path[0] != '\0' ? path : "/run/c300x-root-left-writable";
}

static int left_open(void)
{
    int fd;
    if (root_left_open) {
        return 1;
    }
    fd = open(mark_path(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd >= 0) {
        close(fd);
    }
    return fd >= 0;
}

static void set_left_open(int open_now)
{
    int fd;
    if (!open_now && !left_open()) {
        return;
    }
    root_left_open = open_now;
    if (!open_now) {
        (void)unlink(mark_path());
        return;
    }
    fd = open(mark_path(), O_WRONLY | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd >= 0) {
        close(fd);
    }
}

int c300x_root_remount(const char *mode)
{
    int ok = 1;

    pthread_mutex_lock(&root_lock);
    if (strcmp(mode, "rw") == 0) {
        if (root_writers == 0) {
            root_was_writable = root_is_writable();
            root_foreign = root_was_writable && !left_open();
            if (!root_was_writable) {
                set_left_open(0);
            }
            ok = root_was_writable || root_mount_run("rw");
        }
        root_writers += ok;
    } else {
        root_writers -= root_writers > 0;
        if (root_writers == 0 && !root_foreign) {
            int closed = root_mount_run("ro");
            set_left_open(!closed);
            ok = closed || root_was_writable;
        }
    }
    pthread_mutex_unlock(&root_lock);
    return ok;
}

void c300x_root_close_left_open(void)
{
    pthread_mutex_lock(&root_lock);
    if (root_writers == 0 && left_open() && (!root_is_writable() || root_mount_run("ro"))) {
        set_left_open(0);
    }
    pthread_mutex_unlock(&root_lock);
}
