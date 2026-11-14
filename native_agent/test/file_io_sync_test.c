static int checked_fsync(int fd);
#define fsync checked_fsync
#include "../src/file_io.c"
#undef fsync
extern int fsync(int);
#include <assert.h>

static int synced;
static int fail_sync;

static int checked_fsync(int fd)
{
    synced++;
    if (fail_sync) {
        errno = EIO;
        return -1;
    }
    return fsync(fd);
}

static void put(const char *path, const char *content)
{
    FILE *file = fopen(path, "wb");
    assert(file && fputs(content, file) >= 0 && fclose(file) == 0);
}

int main(int argc, char **argv)
{
    char source[C300X_MAX_PATH_LEN], target[C300X_MAX_PATH_LEN], temporary[C300X_MAX_PATH_LEN + 8];

    assert(argc == 2);
    snprintf(source, sizeof(source), "%s/source", argv[1]);
    snprintf(target, sizeof(target), "%s/target", argv[1]);
    snprintf(temporary, sizeof(temporary), "%s.tmp", target);
    put(source, "payload");

    /* The data reaches the disk before the rename that publishes it. */
    assert(copy_binary_file(source, target, 0600));
    assert(synced == 1);
    /* A staged upload chunk is not synced: its bundle is verified by hash. */
    assert(write_binary_chunk(target, (const unsigned char *)"chunk", 5, 0, 0600));
    assert(synced == 1);

    /* A failed sync is a failed write: no half-published file. */
    unlink(target);
    fail_sync = 1;
    assert(!copy_binary_file(source, target, 0600));
    assert(access(target, F_OK) != 0 && access(temporary, F_OK) != 0);
    assert(write_binary_chunk(target, (const unsigned char *)"chunk", 5, 0, 0600));
    return 0;
}
