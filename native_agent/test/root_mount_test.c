/* Device writers leave / as they found it. */
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <sys/statvfs.h>

#include "../src/device_file.h"
#include "../src/device_patch_io.h"

static int root_read_only;
static char calls[256];

int __wrap_statvfs(const char *path, struct statvfs *info)
{
    assert(strcmp(path, "/") == 0);
    memset(info, 0, sizeof(*info));
    info->f_flag = root_read_only ? ST_RDONLY : 0;
    return 0;
}

int __wrap_system(const char *command)
{
    const char *mode = strstr(command, "remount,");
    assert(mode != NULL && strlen(calls) + 4 < sizeof(calls));
    strncat(calls, mode + 8, 2);
    strcat(calls, " ");
    root_read_only = strncmp(mode + 8, "ro", 2) == 0;
    return 0;
}

static void check(int (*remount)(const char *))
{
    /* Found read-only: writable for the write, read-only again after it. */
    calls[0] = '\0';
    root_read_only = 1;
    assert(remount("rw") == 1 && remount("ro") == 1);
    assert(strcmp(calls, "rw ro ") == 0 && root_read_only);
    /* Found writable: not ours to close; the writer hears it stays so. */
    calls[0] = '\0';
    root_read_only = 0;
    assert(remount("rw") == 1 && remount("ro") == 0);
    assert(strcmp(calls, "") == 0 && !root_read_only);
    /* A later write on a read-only root remounts again. */
    root_read_only = 1;
    assert(remount("rw") == 1 && remount("ro") == 1);
    assert(strcmp(calls, "rw ro ") == 0);
}

/* A write window inside another one (camera rollback around the media
 * geometry patch) neither closes it early nor reports a writable root. */
static void nested(void)
{
    calls[0] = '\0';
    root_read_only = 1;
    assert(c300x_device_file_remount("rw") == 1);
    assert(c300x_patch_remount_root("rw") == 1 && c300x_patch_remount_root("ro") == 1);
    assert(strcmp(calls, "rw ") == 0 && !root_read_only);
    assert(c300x_device_file_remount("ro") == 1);
    assert(strcmp(calls, "rw ro ") == 0 && root_read_only);
}

int main(void)
{
    unsetenv("C300X_AUDIO_NO_REMOUNT");
    unsetenv("C300X_DEVICE_PATCH_NO_REMOUNT");
    check(c300x_device_file_remount);
    check(c300x_patch_remount_root);
    nested();
    return 0;
}
