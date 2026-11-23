#define _LARGEFILE64_SOURCE 1
#include "gui_peer.h"

#include <arpa/inet.h>
#include <dirent.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifdef __arm__
#include <sys/syscall.h>
typedef struct stat64 file_stat;
static int path_stat(const char *path, file_stat *st) { return (int)syscall(SYS_stat64, path, st); }
#else
typedef struct stat file_stat;
static int path_stat(const char *path, file_stat *st) { return stat(path, st); }
#endif

#ifndef C300X_STOCK_GUI
#define C300X_STOCK_GUI "/home/bticino/bin/gui/BtClass"
#endif

/* A loopback address or an HTTP header alone does not identify a physical
 * display action. Find the *client* socket, then verify its executable. */
static unsigned long client_inode(int fd)
{
    struct sockaddr_in peer, local;
    socklen_t n = sizeof(peer);
    if (getpeername(fd, (struct sockaddr *)&peer, &n) || peer.sin_family != AF_INET ||
        peer.sin_addr.s_addr != htonl(INADDR_LOOPBACK) ||
        getsockname(fd, (struct sockaddr *)&local, &n) || local.sin_addr.s_addr != htonl(INADDR_LOOPBACK)) return 0;
    FILE *table = fopen("/proc/net/tcp", "r");
    if (!table) return 0;
    char line[512];
    unsigned long inode = 0;
    while (fgets(line, sizeof(line), table)) {
        unsigned a, p, b, q, state;
        unsigned long candidate;
        if (sscanf(line, " %*u: %x:%x %x:%x %x %*s %*s %*s %*s %*s %lu",
                   &a, &p, &b, &q, &state, &candidate) == 6 &&
            state == 1 && a == peer.sin_addr.s_addr && p == ntohs(peer.sin_port) &&
            b == local.sin_addr.s_addr && q == ntohs(local.sin_port)) { inode = candidate; break; }
    }
    fclose(table);
    return inode;
}

int c300x_stock_gui_peer(int fd)
{
    unsigned long inode = client_inode(fd);
    file_stat trusted, actual;
    if (!inode || path_stat(C300X_STOCK_GUI, &trusted)) return 0;
    DIR *procs = opendir("/proc");
    if (!procs) return 0;
    char socket_name[48];
    snprintf(socket_name, sizeof(socket_name), "socket:[%lu]", inode);
    int found = 0;
    struct dirent *p;
    while (!found && (p = readdir(procs))) {
        size_t len = strlen(p->d_name);
        if (!len || len > 10 || strspn(p->d_name, "0123456789") != len) continue;
        char exe[64], files[64];
        snprintf(exe, sizeof(exe), "/proc/%.10s/exe", p->d_name);
        if (path_stat(exe, &actual) || trusted.st_dev != actual.st_dev || trusted.st_ino != actual.st_ino) continue;
        snprintf(files, sizeof(files), "/proc/%.10s/fd", p->d_name);
        DIR *dir = opendir(files);
        if (!dir) continue;
        struct dirent *entry;
        while ((entry = readdir(dir))) {
            char target[64];
            ssize_t size = readlinkat(dirfd(dir), entry->d_name, target, sizeof(target));
            if (size == (ssize_t)strlen(socket_name) && !memcmp(target, socket_name, (size_t)size)) {
                found = !path_stat(exe, &actual) && trusted.st_dev == actual.st_dev && trusted.st_ino == actual.st_ino;
                break;
            }
        }
        closedir(dir);
    }
    closedir(procs);
    return found;
}
