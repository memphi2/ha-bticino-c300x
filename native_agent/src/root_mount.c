#include "root_mount.h"

#include "pthread_compat.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/statvfs.h>

static pthread_mutex_t root_lock = PTHREAD_MUTEX_INITIALIZER;
static int root_writers, root_found_writable;

static int root_mount_run(const char *mode)
{
    char command[64];
    if (snprintf(command, sizeof(command), "mount -o remount,%s / >/dev/null 2>&1", mode) >= (int)sizeof(command)) {
        return 0;
    }
    return system(command) == 0;
}

int c300x_root_remount(const char *mode)
{
    struct statvfs root;
    int ok = 1;

    pthread_mutex_lock(&root_lock);
    if (strcmp(mode, "rw") == 0) {
        if (root_writers == 0) {
            root_found_writable = statvfs("/", &root) == 0 && (root.f_flag & ST_RDONLY) == 0;
            ok = root_found_writable || root_mount_run("rw");
        }
        root_writers += ok;
    } else {
        root_writers -= root_writers > 0;
        if (root_writers == 0) {
            ok = root_found_writable || root_mount_run("ro");
        }
    }
    pthread_mutex_unlock(&root_lock);
    return ok;
}
