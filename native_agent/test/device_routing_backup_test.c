static char g_target_dir[256];
static char g_backup_dir[256];
static char g_stock_sha[65];
static char g_stock_sha_2_0_2[65];
static int test_remount(const char *mode);
#define C300X_DEVICE_PATCH_TARGET_DIR g_target_dir
#define C300X_DEVICE_PATCH_BACKUP_DIR g_backup_dir
#define C300X_DEVICE_PATCH_STOCK_SHA256 g_stock_sha
#define C300X_DEVICE_PATCH_STOCK_SHA256_2_0_2 g_stock_sha_2_0_2
#define c300x_patch_remount_root test_remount
#define c300x_patch_range_matches test_range_matches
#include "../src/device_routing.c"
#undef c300x_patch_remount_root
#undef c300x_patch_range_matches
#include <assert.h>

/* The stock bytes of the real ranges cannot be built here. A backup "has"
 * them when the test says so. */
static int g_ranges_match;
/* With a table set, only that firmware's ranges match, in the given state. */
static const struct c300x_patch_range *g_ranges_table;
static int g_ranges_patched;
int test_range_matches(const unsigned char *data, size_t len,
                       const struct c300x_patch_range *patch, const char *sha256)
{
    (void)data; (void)len;
    if (g_ranges_table != NULL) {
        return patch >= g_ranges_table && patch < g_ranges_table + ARRAY_LEN(PATCHES)
            && sha256 == (g_ranges_patched
                ? patch->patched_range_sha256 : patch->expected_range_sha256);
    }
    return g_ranges_match;
}

static int test_remount(const char *mode)
{
    (void)mode;
    return 1;
}

static void put(const char *path, const char *content)
{
    FILE *file = fopen(path, "wb");
    assert(file && fputs(content, file) >= 0 && fclose(file) == 0);
}

static void expect(const char *path, const char *content)
{
    char buffer[64] = "";
    FILE *file = fopen(path, "rb");
    assert(file);
    assert(fgets(buffer, sizeof(buffer), file) != NULL || content[0] == '\0');
    fclose(file);
    assert(strcmp(buffer, content) == 0);
}

int main(int argc, char **argv)
{
    char target[C300X_MAX_PATH_LEN], backup[C300X_MAX_PATH_LEN];
    char error[64];
    struct c300x_device_routing_status status;

    assert(argc == 2);
    snprintf(g_target_dir, sizeof(g_target_dir), "%s/bin", argv[1]);
    snprintf(g_backup_dir, sizeof(g_backup_dir), "%s/backup", argv[1]);
    assert(mkdir(g_target_dir, 0755) == 0 && mkdir(g_backup_dir, 0755) == 0);
    assert(device_patch_target_path(target, sizeof(target)));
    assert(device_patch_backup_path(backup, sizeof(backup)));

    /* A valid backup restores the target. */
    put(backup, "stock-binary");
    assert(c300x_sha256_file_hex(backup, g_stock_sha, sizeof(g_stock_sha)));
    put(target, "modified");
    error[0] = '\0';
    assert(c300x_device_routing_restore(&status, error, sizeof(error)));
    expect(target, "stock-binary");

    /* A backup that is not the stock file must not replace the target. */
    put(backup, "garbage");
    put(target, "modified");
    assert(!c300x_device_routing_restore(&status, error, sizeof(error)));
    assert(strcmp(error, "routing_backup_invalid") == 0);
    expect(target, "modified");

    /* A backup of another build passes by its ranges, when it is complete. */
    g_ranges_match = 1;
    put(backup, "other-build!");
    put(target, "modified-123");
    assert(c300x_device_routing_restore(&status, error, sizeof(error)));
    expect(target, "other-build!");

    /* A copy that was cut off behind the last range still has the ranges,
     * but it is shorter than the file: it must not replace the target. */
    put(backup, "other-b");
    put(target, "modified-123");
    assert(!c300x_device_routing_restore(&status, error, sizeof(error)));
    assert(strcmp(error, "routing_backup_invalid") == 0);
    expect(target, "modified-123");
    g_ranges_match = 0;

    /* The stock 2.0.2 file is recognised by its own hash. */
    put(target, "stock-2-0-2");
    assert(c300x_sha256_file_hex(target, g_stock_sha_2_0_2, sizeof(g_stock_sha_2_0_2)));
    assert(c300x_device_routing_read_status(&status));
    assert(strcmp(status.state, "stock") == 0);

    /* So is its backup. */
    put(backup, "stock-2-0-2");
    put(target, "modified-202");
    assert(c300x_device_routing_restore(&status, error, sizeof(error)));
    expect(target, "stock-2-0-2");

    /* A file that is neither build stays unsupported. */
    put(target, "another-file");
    assert(c300x_device_routing_read_status(&status));
    assert(strcmp(status.state, "unsupported") == 0);

    /* The backup of the other firmware is a stock file, but not of this
     * device: it must not be written over the 2.0.2 target. */
    put(backup, "stock-binary");
    put(target, "stock-2-0-2");
    assert(!c300x_device_routing_restore(&status, error, sizeof(error)));
    assert(strcmp(error, "routing_backup_invalid") == 0);
    expect(target, "stock-2-0-2");

    /* Nor over a patched 2.0.2 target, which is known by its ranges. */
    put(target, "patched-2-0-2");
    g_ranges_table = PATCHES_2_0_2;
    g_ranges_patched = 1;
    assert(c300x_device_routing_read_status(&status));
    assert(strcmp(status.state, "patched") == 0);
    assert(!c300x_device_routing_restore(&status, error, sizeof(error)));
    assert(strcmp(error, "routing_backup_invalid") == 0);
    expect(target, "patched-2-0-2");
    g_ranges_table = NULL;

    /* A backup that has the stock ranges of the other firmware only. */
    put(backup, "ranges-1-7-19");
    put(target, "stock-2-0-2xx");
    assert(c300x_sha256_file_hex(target, g_stock_sha_2_0_2, sizeof(g_stock_sha_2_0_2)));
    g_ranges_table = PATCHES;
    assert(!c300x_device_routing_restore(&status, error, sizeof(error)));
    assert(strcmp(error, "routing_backup_invalid") == 0);
    expect(target, "stock-2-0-2xx");
    g_ranges_table = NULL;

    /* Applying on 2.0.2 replaces the backup the other firmware left behind. */
    put(backup, "stock-binary");
    put(target, "stock-2-0-2");
    assert(c300x_sha256_file_hex(target, g_stock_sha_2_0_2, sizeof(g_stock_sha_2_0_2)));
    (void)c300x_device_routing_apply(&status, error, sizeof(error));
    expect(backup, "stock-2-0-2");

    /* Applying over a stock target replaces a backup that is not stock. */
    put(target, "stock-binary");
    put(backup, "garbage");
    (void)c300x_device_routing_apply(&status, error, sizeof(error));
    expect(backup, "stock-binary");
    return 0;
}
