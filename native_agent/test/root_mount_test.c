/* Device writers leave / as they found it. */
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <sys/statvfs.h>
#include <unistd.h>

#include "../src/device_file.h"
#include "../src/device_patch_io.h"
#include "../src/root_mount.h"

static int root_read_only, ro_busy;
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
    if (ro_busy && strncmp(mode + 8, "ro", 2) == 0) {
        return 256;
    }
    root_read_only = strncmp(mode + 8, "ro", 2) == 0;
    return 0;
}

static int marked(void)
{
    return access(getenv("C300X_ROOT_LEFT_OPEN_MARK"), F_OK) == 0;
}

/* Routing replaced a binary the vendor process still runs: "ro" is busy. */
static void leave_open(void)
{
    calls[0] = '\0';
    root_read_only = 1;
    ro_busy = 1;
    assert(c300x_patch_remount_root("rw") == 1 && c300x_patch_remount_root("ro") == 0);
    assert(strcmp(calls, "rw ro ") == 0 && !root_read_only && marked());
    ro_busy = 0;
}

/* The root this agent left writable stays its own: a later window (here a
 * firewall or codec write after the vendor process exited) closes it. Before,
 * it counted as found writable and / stayed writable until a reboot. */
static void left_open_is_closed_later(void)
{
    leave_open();
    /* Still busy: the retry fails, but / was writable when it started. */
    calls[0] = '\0';
    ro_busy = 1;
    assert(c300x_device_file_remount("rw") == 1 && c300x_device_file_remount("ro") == 1);
    assert(strcmp(calls, "ro ") == 0 && !root_read_only && marked());
    ro_busy = 0;
    calls[0] = '\0';
    assert(c300x_device_file_remount("rw") == 1 && c300x_device_file_remount("ro") == 1);
    assert(strcmp(calls, "ro ") == 0 && root_read_only && !marked());
    /* Writable by someone else afterwards: not ours again. */
    calls[0] = '\0';
    root_read_only = 0;
    assert(c300x_device_file_remount("rw") == 1 && c300x_device_file_remount("ro") == 1);
    assert(strcmp(calls, "") == 0 && !root_read_only);
    /* The agent update check closes it before refusing a writable root. */
    leave_open();
    calls[0] = '\0';
    c300x_root_close_left_open();
    assert(strcmp(calls, "ro ") == 0 && root_read_only && !marked());
    calls[0] = '\0';
    root_read_only = 0;
    c300x_root_close_left_open();
    assert(strcmp(calls, "") == 0 && !root_read_only);
}

static void check(int (*remount)(const char *))
{
    /* Found read-only: writable for the write, read-only again after it. */
    calls[0] = '\0';
    root_read_only = 1;
    assert(remount("rw") == 1 && remount("ro") == 1);
    assert(strcmp(calls, "rw ro ") == 0 && root_read_only);
    /* Found writable: not ours to close, and leaving it so is success
     * (a removal once stopped and asked for a reboot over it). */
    calls[0] = '\0';
    root_read_only = 0;
    assert(remount("rw") == 1 && remount("ro") == 1);
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

int main(int argc, char **argv)
{
    unsetenv("C300X_AUDIO_NO_REMOUNT");
    unsetenv("C300X_DEVICE_PATCH_NO_REMOUNT");
    assert(getenv("C300X_ROOT_LEFT_OPEN_MARK") != NULL);
    if (argc > 1 && strcmp(argv[1], "leave") == 0) {
        leave_open();
        return 0;
    }
    if (argc > 1 && strcmp(argv[1], "restarted") == 0) {
        /* A new agent process (self-update) finds the writable root. */
        root_read_only = 0;
        assert(marked());
        assert(c300x_patch_remount_root("rw") == 1 && c300x_patch_remount_root("ro") == 1);
        assert(strcmp(calls, "ro ") == 0 && root_read_only && !marked());
        return 0;
    }
    check(c300x_device_file_remount);
    check(c300x_patch_remount_root);
    nested();
    left_open_is_closed_later();
    return 0;
}
