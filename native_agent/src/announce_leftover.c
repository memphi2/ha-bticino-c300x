#include "announce_device.h"
#include "announce_file.h"

#include <dirent.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* The play script of an agent that was killed outright, found by its name and
 * its sound file: it would hold the sound device and leave the speaker on. */
static int leftover(const char *pid_name, const char *file)
{
    char path[64], args[4096], line[128];
    const char *want[] = {"/bin/sh", "-c", NULL, "c300x-announce", file};
    size_t len, at = 0;
    int uid = -1, ok = 1;
    FILE *in;

    snprintf(path, sizeof(path), "/proc/%s/status", pid_name);
    if ((in = fopen(path, "r")) == NULL) {
        return 0;
    }
    while (fgets(line, sizeof(line), in) != NULL && sscanf(line, "Uid: %d", &uid) != 1) {
    }
    fclose(in);
    snprintf(path, sizeof(path), "/proc/%s/cmdline", pid_name);
    if (uid != (int)getuid() || (in = fopen(path, "r")) == NULL) {
        return 0;
    }
    len = fread(args, 1, sizeof(args) - 1, in);
    fclose(in);
    args[len] = '\0';
    for (int i = 0; i < 5 && ok; i++) {
        ok = at < len && (want[i] == NULL || strcmp(args + at, want[i]) == 0);
        at += strlen(args + at) + 1;
    }
    return ok;
}

int c300x_announce_end_leftover(void)
{
    DIR *proc = opendir("/proc");
    struct dirent *entry;
    int found = 0;

    while (proc != NULL && (entry = readdir(proc)) != NULL) {
        pid_t pid = (pid_t)atoi(entry->d_name);
        if (pid > 1 && pid != getpid() && getpgid(pid) == pid && leftover(entry->d_name, c300x_announce_file())) {
            found = kill(-pid, SIGKILL) == 0 || found;
        }
    }
    if (proc != NULL) {
        closedir(proc);
    }
    return found;
}
