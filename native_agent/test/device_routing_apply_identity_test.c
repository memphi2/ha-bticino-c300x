/* Separate from restore/removal fixtures: writable paths must be temp copies. */
static const char *target_dir, *backup_dir;
#define C300X_DEVICE_PATCH_TARGET_DIR target_dir
#define C300X_DEVICE_PATCH_BACKUP_DIR backup_dir
#include <errno.h>
#include <stdlib.h>
#include <unistd.h>
/* C300X_TEST_FSYNC_FAIL: the patched copy cannot be synced to disk. */
static int test_fsync(int fd)
{
    if (getenv("C300X_TEST_FSYNC_FAIL") != NULL) {
        errno = EIO;
        return -1;
    }
    return fsync(fd);
}
#define fsync test_fsync
#undef _POSIX_C_SOURCE
#include "../src/device_routing.c"
#undef fsync
#include <assert.h>

int main(int argc, char **argv)
{
    assert(argc == 4);
    target_dir = argv[1];
    backup_dir = argv[2];
    assert(getenv("C300X_DEVICE_PATCH_NO_REMOUNT") != NULL);
    struct c300x_device_routing_status status = {0};
    char error[128] = "";
    int ok;
    if (strcmp(argv[3], "status") == 0) {
        ok = c300x_device_routing_read_status(&status);
    } else if (strcmp(argv[3], "apply") == 0) {
        ok = c300x_device_routing_apply(&status, error, sizeof(error));
    } else {
        assert(strcmp(argv[3], "restore") == 0);
        ok = c300x_device_routing_restore(&status, error, sizeof(error));
    }
    printf("ok=%d state=%s patched=%d error=%s root_writable=%d\n", ok, status.state, status.patched,
           error, status.root_writable);
    return ok ? 0 : 1;
}
