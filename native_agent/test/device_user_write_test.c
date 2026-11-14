static int checked_fsync(int fd);
static int checked_fchmod(int fd, unsigned int mode);
#define fsync checked_fsync
#define fchmod checked_fchmod
#include "../src/device_user.c"
#undef fsync
#undef fchmod
#include <assert.h>
extern int fsync(int);
extern int fchmod(int, mode_t);

static long expected_len;
static int synced;
static int fail_sync;

static int checked_fsync(int fd)
{
    struct stat status;
    assert(fstat(fd, &status) == 0);
    /* Everything is on the file, not left in the stdio buffer. */
    assert(status.st_size == expected_len);
    synced++;
    if (fail_sync) {
        errno = EIO;
        return -1;
    }
    return fsync(fd);
}

static int checked_fchmod(int fd, unsigned int mode)
{
    struct stat status;
    assert(fstat(fd, &status) == 0);
    /* Never readable by others before the final mode is set. */
    assert((status.st_mode & 0077) == 0);
    return fchmod(fd, (mode_t)mode);
}

int main(int argc, char **argv)
{
    char path[C300X_MAX_PATH_LEN], tmp[C300X_MAX_PATH_LEN + 16], error[64] = "";
    struct stat status;
    FILE *fp;
    char buffer[64] = "";

    assert(argc == 2);
    snprintf(path, sizeof(path), "%s/accounts.txt", argv[1]);
    snprintf(tmp, sizeof(tmp), "%s.c300x-ha.tmp", path);
    umask(0);

    expected_len = 12;
    assert(write_file_atomic(path, "Alice|alice\n", 12, 0644, error, sizeof(error)));
    assert(synced == 1);
    assert(stat(path, &status) == 0 && (status.st_mode & 0777) == 0644);
    fp = fopen(path, "r");
    assert(fp && fgets(buffer, sizeof(buffer), fp) && fclose(fp) == 0);
    assert(strcmp(buffer, "Alice|alice\n") == 0);
    assert(access(tmp, F_OK) != 0);

    /* A stale temporary file of an earlier crash does not block the write. */
    fp = fopen(tmp, "w");
    assert(fp && fputs("stale", fp) >= 0 && fclose(fp) == 0);
    assert(write_file_atomic(path, "Alice|alice\n", 12, 0600, error, sizeof(error)));
    assert(stat(path, &status) == 0 && (status.st_mode & 0777) == 0600);

    /* A failing sync is a failed write: the old file stays, no temporary file. */
    fail_sync = 1;
    expected_len = 8;
    assert(!write_file_atomic(path, "Bob|bob\n", 8, 0600, error, sizeof(error)));
    assert(strcmp(error, "tmp_sync_failed") == 0);
    assert(access(tmp, F_OK) != 0);
    fp = fopen(path, "r");
    assert(fp && fgets(buffer, sizeof(buffer), fp) && fclose(fp) == 0);
    assert(strcmp(buffer, "Alice|alice\n") == 0);
    return 0;
}
