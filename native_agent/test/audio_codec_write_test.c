#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
#include <assert.h>
#include <dirent.h>
#include <fcntl.h>

static size_t checked_write(const void *, size_t, size_t, FILE *);
static FILE *checked_fdopen(int, const char *);
static int checked_sync(int);
static int checked_rename(const char *, const char *);
#define fwrite checked_write
#define fdopen checked_fdopen
#define fsync checked_sync
#define rename checked_rename
#include "../src/device_file.c"
#include "../src/audio_codec.c"
#undef fwrite
#undef fdopen
#undef fsync
#undef rename

static int failure, last_fd;
static size_t checked_write(const void *data, size_t size, size_t count, FILE *fp) {
    struct stat st;
    assert(fstat(fileno(fp), &st) == 0 && (st.st_mode & 0777) == 0600);
    assert(fcntl(fileno(fp), F_GETFD) & FD_CLOEXEC);
    if (failure == 2) return 0;
    return fwrite(data, size, count, fp);
}
static FILE *checked_fdopen(int fd, const char *mode) {
    last_fd = fd;
    if (failure == 1) { errno = ENOMEM; return NULL; }
    return fdopen(fd, mode);
}
static int checked_sync(int fd) {
    if (failure == 3) { errno = EIO; return -1; }
    return fsync(fd);
}
static int checked_rename(const char *from, const char *to) {
    if (failure == 4) { errno = EIO; return -1; }
    return rename(from, to);
}
static void check_file(const char *path, const char *expected, mode_t mode) {
    char data[1024] = {0};
    struct stat st;
    FILE *fp = fopen(path, "rb");
    assert(fp && fread(data, 1, sizeof(data) - 1, fp) == strlen(expected));
    assert(fclose(fp) == 0 && strcmp(data, expected) == 0);
    assert(stat(path, &st) == 0 && (st.st_mode & 0777) == mode);
    assert(st.st_uid == getuid() && st.st_gid == getgid());
}
int main(int argc, char **argv) {
    assert(argc == 2);
    assert(chdir(argv[1]) == 0);
    umask(0);
    assert(c300x_device_file_write("codec", "old", 3));
    check_file("codec", "old", 0600);
    /* A stale predictable symlink must not redirect or prevent the write. */
    assert(symlink("codec", "codec.tmp") == 0);
    for (failure = 1; failure <= 4; failure++) {
        assert(!c300x_device_file_write("codec", "new", 3));
        assert(fcntl(last_fd, F_GETFD) == -1 && errno == EBADF);
        check_file("codec", "old", 0600);
        DIR *dir = opendir(".");
        assert(dir);
        struct dirent *entry;
        while ((entry = readdir(dir)) != NULL) {
            assert(strncmp(entry->d_name, "codec.tmp.", 10) != 0);
        }
        closedir(dir);
    }
    failure = 0;
    assert(chmod("codec", 0640) == 0);
    assert(c300x_device_file_write("codec", "new", 3));
    check_file("codec", "new", 0640);
    assert(c300x_device_file_copy("codec", "backup"));
    check_file("backup", "new", 0640);
    /* Exercise actual apply/restore with synthetic config and remount disabled. */
    const char *stack = "<media>\n<enable_speex>1</enable_speex>\n"
        "<audio_compression>1</audio_compression>\n</media>\n";
    const char *linphone = "[sound]\nrtp_io=1\nrtp_ptnum=110\nrtp_map=speex/8000/1\n"
        "[audio_codec_0]\nmime=PCMU\nrate=8000\nchannels=1\nenabled=0\n"
        "[audio_codec_1]\nmime=speex\nrate=8000\nchannels=1\nenabled=1\n";
    assert(setenv("C300X_AUDIO_STACK_OPEN", "stack.xml", 1) == 0);
    assert(setenv("C300X_AUDIO_LINPHONE_CONF", "linphone.conf", 1) == 0);
    assert(setenv("C300X_AUDIO_BACKUP_DIR", "original", 1) == 0);
    assert(setenv("C300X_AUDIO_NO_REMOUNT", "1", 1) == 0);
    assert(c300x_device_file_write("stack.xml", stack, strlen(stack)));
    assert(c300x_device_file_write("linphone.conf", linphone, strlen(linphone)));
    struct c300x_audio_codec_status status;
    char error[128];
    assert(c300x_audio_codec_apply(&status, error, sizeof(error)));
    assert(strcmp(status.state, "pcmu") == 0);
    assert(c300x_audio_codec_restore(&status, error, sizeof(error)));
    check_file("stack.xml", stack, 0600);
    check_file("linphone.conf", linphone, 0600);
    return 0;
}
