#define _LARGEFILE64_SOURCE 1
#include "gui_peer.h"

#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>

#ifdef __arm__
#include <sys/syscall.h>
typedef struct stat64 file_stat;
static int path_stat(const char *path, file_stat *st) { return (int)syscall(SYS_stat64, path, st); }
#else
typedef struct stat file_stat;
static int path_stat(const char *path, file_stat *st) { return stat(path, st); }
#endif

#ifndef C300X_GUI_HOME
#define C300X_GUI_HOME "/home/bticino"
#endif
#ifndef C300X_GUI_UID
#define C300X_GUI_UID 0
#define C300X_GUI_GID 0
#endif
#ifndef C300X_GUI_INIT_PID
#define C300X_GUI_INIT_PID 1
#endif

/* A loopback address or an HTTP header alone does not identify a physical
 * display action. Find the *client* socket, then verify its executable. */
static unsigned long long client_inode(int fd)
{
    struct sockaddr_in peer, local;
    socklen_t n = sizeof(peer);
    if (getpeername(fd, (struct sockaddr *)&peer, &n) || peer.sin_family != AF_INET ||
        peer.sin_addr.s_addr != htonl(INADDR_LOOPBACK) ||
        getsockname(fd, (struct sockaddr *)&local, &n) || local.sin_addr.s_addr != htonl(INADDR_LOOPBACK)) return 0;
    FILE *table = fopen("/proc/net/tcp", "r");
    if (!table) return 0;
    char line[512];
    unsigned long long inode = 0;
    while (fgets(line, sizeof(line), table)) {
        unsigned a, p, b, q, state, uid;
        unsigned long long candidate;
        if (sscanf(line, " %*u: %x:%x %x:%x %x %*s %*s %*s %u %*s %llu",
                   &a, &p, &b, &q, &state, &uid, &candidate) == 7 && uid == C300X_GUI_UID &&
            state == 1 && a == peer.sin_addr.s_addr && p == ntohs(peer.sin_port) &&
            b == local.sin_addr.s_addr && q == ntohs(local.sin_port)) { inode = candidate; break; }
    }
    fclose(table);
    return inode;
}

static int open_process(unsigned pid)
{
    char path[64];
    snprintf(path, sizeof(path), "/proc/%u", pid);
    return open(path, O_DIRECTORY | O_RDONLY | O_CLOEXEC);
}

/* Resolve through a pinned proc directory, not a reusable numeric PID. */
static int same_file(int proc, const char *entry, const char *expected)
{
    char path[64];
    file_stat actual, trusted;
    snprintf(path, sizeof(path), "/proc/self/fd/%d/%s", proc, entry);
    return !path_stat(path, &actual) && !path_stat(expected, &trusted) &&
           actual.st_dev == trusted.st_dev && actual.st_ino == trusted.st_ino;
}

static unsigned trusted_parent(int proc)
{
    int fd = openat(proc, "status", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    FILE *status = fdopen(fd, "r");
    if (!status) { close(fd); return 0; }
    unsigned parent = 0;
    int uid = 0, gid = 0;
    char line[256];
    while (fgets(line, sizeof(line), status)) {
        unsigned a, b, c, d;
        if (sscanf(line, "PPid: %u", &a) == 1) parent = a;
        if (sscanf(line, "Uid: %u %u %u %u", &a, &b, &c, &d) == 4)
            uid = a == C300X_GUI_UID && a == b && a == c && a == d;
        if (sscanf(line, "Gid: %u %u %u %u", &a, &b, &c, &d) == 4)
            gid = a == C300X_GUI_GID && a == b && a == c && a == d;
    }
    int valid = uid && gid && !ferror(status);
    fclose(status);
    return valid ? parent : 0;
}

static int wrapper_script_open(int proc)
{
    int fd = openat(proc, "fd", O_DIRECTORY | O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    DIR *dir = fdopendir(fd);
    if (!dir) { close(fd); return 0; }
    struct dirent *entry;
    int found = 0;
    while ((entry = readdir(dir))) {
        if (!entry->d_name[0] || strlen(entry->d_name) > 10 ||
            strspn(entry->d_name, "0123456789") != strlen(entry->d_name)) continue;
        if (same_file(fd, entry->d_name, C300X_GUI_HOME "/bin/BtClass_qws")) {
            found = 1;
            break;
        }
    }
    closedir(dir);
    return found;
}

enum launch { UNKNOWN, STOCK, RELOAD };

static enum launch stock_wrapper(int proc)
{
    static const char relative[] = "/bin/sh\0bin/BtClass_qws";
    static const char absolute[] = "/bin/sh\0" C300X_GUI_HOME "/bin/BtClass_qws";
    char data[sizeof(absolute) + 1];
    int fd = openat(proc, "cmdline", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    size_t used = 0;
    while (used < sizeof(data)) {
        ssize_t n = read(fd, data + used, sizeof(data) - used);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) { close(fd); return UNKNOWN; }
        if (!n) break;
        used += (size_t)n;
    }
    close(fd);
    if (!same_file(proc, "exe", "/bin/sh") || !same_file(proc, "cwd", C300X_GUI_HOME) ||
        !wrapper_script_open(proc)) return UNKNOWN;
    if (used == sizeof(relative) && !memcmp(data, relative, sizeof(relative))) return STOCK;
    if (used == sizeof(absolute) && !memcmp(data, absolute, sizeof(absolute))) return RELOAD;
    return UNKNOWN;
}

static unsigned daemon_parent(int proc)
{
    return same_file(proc, "exe", C300X_GUI_HOME "/bin/bt_daemon") ? trusted_parent(proc) : 0;
}

/* Stock launches the wrapper under one daemon, or under a fork of that daemon. */
static int stock_daemons(unsigned pid)
{
    int child = open_process(pid);
    if (child < 0) return 0;
    unsigned parent = daemon_parent(child);
    int ok = parent == C300X_GUI_INIT_PID;
    if (parent && !ok) {
        int supervisor = open_process(parent);
        if (supervisor >= 0) {
            ok = daemon_parent(supervisor) == C300X_GUI_INIT_PID && daemon_parent(child) == parent;
            close(supervisor);
        }
    }
    close(child);
    return ok;
}

static int station_gui(int gui)
{
    if (!same_file(gui, "exe", C300X_GUI_HOME "/bin/gui/BtClass")) return 0;
    unsigned wrapper_pid = trusted_parent(gui);
    int wrapper = wrapper_pid ? open_process(wrapper_pid) : -1;
    if (wrapper < 0) return 0;
    enum launch launch = stock_wrapper(wrapper);
    unsigned parent = trusted_parent(wrapper);
    /* reload_gui starts the absolute wrapper directly; init adopts it.
     * Never use orphanhood alone as the proof of a station launch. */
    int ok = ((launch == RELOAD && parent == C300X_GUI_INIT_PID) ||
              (launch == STOCK && parent && stock_daemons(parent))) &&
             trusted_parent(wrapper) == parent && trusted_parent(gui) == wrapper_pid;
    close(wrapper);
    return ok;
}

static int owns_socket(int gui, const char *socket_name)
{
    int fd = openat(gui, "fd", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) return 0;
    DIR *dir = fdopendir(fd);
    if (!dir) { close(fd); return 0; }
    int found = 0;
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        char target[64];
        ssize_t size = readlinkat(fd, entry->d_name, target, sizeof(target));
        if (size == (ssize_t)strlen(socket_name) && !memcmp(target, socket_name, (size_t)size)) {
            found = 1;
            break;
        }
    }
    closedir(dir);
    return found;
}

int c300x_stock_gui_peer(int fd)
{
    unsigned long long inode = client_inode(fd);
    if (!inode) return 0;
    /* The vendor owns these files as 1000:1000, not root. Do not use a
     * mutable firmware tree as an identity anchor during maintenance. */
    const char *anchors[] = {C300X_GUI_HOME "/bin/BtClass_qws", C300X_GUI_HOME "/bin/gui/BtClass",
                             C300X_GUI_HOME "/bin/bt_daemon"};
    for (size_t i = 0; i < sizeof(anchors) / sizeof(anchors[0]); ++i) {
        struct statvfs fs;
        if (statvfs(anchors[i], &fs) || !(fs.f_flag & ST_RDONLY)) return 0;
    }
    DIR *procs = opendir("/proc");
    if (!procs) return 0;
    int candidate = -1, ok = 0;
    for (;;) {
        errno = 0;
        struct dirent *p = readdir(procs);
        if (!p) { ok = !errno && candidate >= 0; break; }
        if (!p->d_name[0] || strspn(p->d_name, "0123456789") != strlen(p->d_name)) continue;
        int gui = openat(dirfd(procs), p->d_name, O_DIRECTORY | O_RDONLY | O_CLOEXEC);
        if (gui < 0) continue;
        if (station_gui(gui)) {
            if (candidate >= 0) { close(gui); break; }
            candidate = gui;
        } else close(gui);
    }
    closedir(procs);
    char socket_name[48];
    snprintf(socket_name, sizeof(socket_name), "socket:[%llu]", inode);
    ok = ok && owns_socket(candidate, socket_name) && station_gui(candidate);
    if (candidate >= 0) close(candidate);
    return ok;
}
