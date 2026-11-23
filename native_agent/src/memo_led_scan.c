#define _GNU_SOURCE 1
#include "memo_led_scan.h"
#include "c300x_agent.h"
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/eventfd.h>
#include <sys/inotify.h>
#include <sys/stat.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <unistd.h>

#define DIR_FLAGS (O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC | O_RDONLY)
#define MAX_ENTRIES 512
#define MAX_INFO 4096

struct memo_scan {
    pthread_t thread;
    char roots[2][C300X_MAX_PATH_LEN];
    int done, watch, result;
};

static int watch_dir(int watch, int fd, int items)
{
    char path[64];
    snprintf(path, sizeof(path), "/proc/self/fd/%d", fd);
    return inotify_add_watch(watch, path, IN_CREATE | IN_DELETE | IN_MOVED_FROM |
            IN_MOVED_TO | IN_MOVE_SELF | IN_DELETE_SELF | IN_MASK_ADD |
            (items ? IN_CLOSE_WRITE | IN_MODIFY | IN_ATTRIB : 0)) >= 0;
}

static char *trim(char *s)
{
    while (isspace((unsigned char)*s)) ++s;
    char *end = s + strlen(s);
    while (end > s && isspace((unsigned char)end[-1])) --end;
    *end = 0;
    return s;
}

static int unread_info(int dir)
{
    /* Pin the inode without invoking a FIFO/device open handler. Reopen
     * that exact inode only after checking type and size. */
    int fd = openat(dir, "msg_info.ini", O_PATH | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return -1;
#ifdef __arm__
    struct stat64 st;
    int ok = syscall(SYS_fstat64, fd, &st) == 0;
#else
    struct stat st;
    int ok = fstat(fd, &st) == 0;
#endif
    char buf[MAX_INFO + 1];
    int input = -1;
    if (ok && S_ISREG(st.st_mode) && st.st_size > 0 && st.st_size <= MAX_INFO) {
        char path[64];
        snprintf(path, sizeof(path), "/proc/self/fd/%d", fd);
        input = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    }
    close(fd);
    if (input < 0) return -1;
    ssize_t n = read(input, buf, sizeof(buf));
    close(input);
    if (n <= 0 || n != st.st_size || n > MAX_INFO || memchr(buf, 0, n)) return -1;
    buf[n] = 0;
    int section = 0, result = -1;
    char *rest = buf, *line;
    while ((line = strsep(&rest, "\n"))) {
        line = trim(line);
        if (*line == '[') section = !strcmp(line, "[Message Information]");
        else if (section) {
            char *value = strchr(line, '=');
            if (!value) continue;
            *value++ = 0;
            if (strcasecmp(trim(line), "Read")) continue;
            value = trim(value);
            if (result >= 0 || (strcmp(value, "0") && strcmp(value, "1"))) return -1;
            result = *value == '0';
        }
    }
    return result;
}

static int open_root(const char *root, int watch)
{
    char path[C300X_MAX_PATH_LEN];
    snprintf(path, sizeof(path), "%s", root);
    char *rest = path, *name;
    int fd = open(*root == '/' ? "/" : ".", DIR_FLAGS);
    while (fd >= 0 && (name = strsep(&rest, "/"))) {
        if (!*name || !strcmp(name, ".")) continue;
        if (!strcmp(name, "..")) { close(fd); return -1; }
        if (!rest && !watch_dir(watch, fd, 0)) { close(fd); return -1; }
        int child = openat(fd, name, DIR_FLAGS);
        if (child < 0 && watch_dir(watch, fd, 0))
            child = openat(fd, name, DIR_FLAGS);
        close(fd);
        fd = child;
    }
    return fd;
}

static int scan_root(const char *root, int watch)
{
    if (!*root) return -1;
    int fd = open_root(root, watch);
    if (fd < 0) return -1;
    int reliable = watch_dir(watch, fd, 1);
    DIR *dir = fdopendir(fd);
    if (!dir) { close(fd); return -1; }
    int result = 0;
    for (unsigned i = 0;; ++i) {
        errno = 0;
        struct dirent *entry = readdir(dir);
        if (!entry) { if (errno) result = -1; break; }
        if (i >= MAX_ENTRIES) { result = -1; break; }
        if (entry->d_name[0] == '.') continue;
        int item = openat(fd, entry->d_name, DIR_FLAGS);
        if (item < 0) {
            if (entry->d_type != DT_REG || errno != ENOTDIR) result = -1;
            continue;
        }
        reliable &= watch_dir(watch, item, 1);
        int unread = unread_info(item);
        close(item);
        if (unread == 1) { result = 1; break; }
        if (unread < 0) result = -1;
    }
    closedir(dir);
    return reliable ? result : -1;
}

static void *worker(void *arg)
{
    struct memo_scan *s = arg;
    int text = scan_root(s->roots[0], s->watch);
    int voice = text == 1 ? 0 : scan_root(s->roots[1], s->watch);
    s->result = text == 1 || voice == 1 ? 1 : text < 0 || voice < 0 ? -1 : 0;
    while (eventfd_write(s->done, 1) < 0 && errno == EINTR) {}
    return NULL;
}

struct memo_scan *memo_scan_start(const char *text, const char *voice, int *completion)
{
    struct memo_scan *s = calloc(1, sizeof(*s));
    if (!s) return NULL;
    snprintf(s->roots[0], sizeof(s->roots[0]), "%s", text);
    snprintf(s->roots[1], sizeof(s->roots[1]), "%s", voice);
    s->done = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
    s->watch = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
    if (s->done < 0 || s->watch < 0 || pthread_create(&s->thread, NULL, worker, s)) {
        if (s->done >= 0) close(s->done);
        if (s->watch >= 0) close(s->watch);
        free(s);
        return NULL;
    }
    *completion = s->done;
    return s;
}

int memo_scan_finish(struct memo_scan *s, int *watch)
{
    pthread_join(s->thread, NULL);
    int result = s->result;
    close(s->done);
    *watch = s->watch;
    free(s);
    return result;
}
