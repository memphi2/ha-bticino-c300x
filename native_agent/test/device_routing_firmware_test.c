/* Real patch/restore code; all writable paths are supplied by the temp fixture. */
static const char *target_dir, *backup_dir;
static int test_rename(const char *source, const char *target);
#define C300X_DEVICE_PATCH_TARGET_DIR target_dir
#define C300X_DEVICE_PATCH_BACKUP_DIR backup_dir
#define rename test_rename
#include "../src/device_routing.c"
#undef rename
#include <assert.h>

int rename(const char *source, const char *target);
static int test_rename(const char *source, const char *target)
{
    if (getenv("TEST_RENAME_FAIL")) {
        errno = EIO;
        return -1;
    }
    return rename(source, target);
}

int main(int argc, char **argv)
{
    assert(argc == 4);
    target_dir = argv[1];
    backup_dir = argv[2];
    assert(getenv("C300X_DEVICE_PATCH_NO_REMOUNT") != NULL);
    struct c300x_device_routing_status status = {0};
    char error[128] = "";
    int ok = strcmp(argv[3], "apply") == 0
        ? c300x_device_routing_apply(&status, error, sizeof(error))
        : c300x_device_routing_restore(&status, error, sizeof(error));
    printf("ok=%d state=%s error=%s\n", ok, status.state, error);
    return ok ? 0 : 1;
}
