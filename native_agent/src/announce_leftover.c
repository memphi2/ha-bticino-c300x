#include "announce_device.h"
#include "announce_file.h"

#include <dirent.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* A play script or switching off of an agent that was killed or restarted,
 * found by its name and its sound file. A play script would hold the sound
 * device and leave the speaker on; a switching off would act behind the new
 * agent's back. The gain a switching off was to set back is taken over. */
static int leftover(const char *pid_name, const char *file, int *gain)
{
    char path[64], args[4096], line[128];
    const char *word[7] = {NULL};
    size_t len, at = 0;
    int uid = -1, words = 0;
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
    for (; words < 7 && at < len; at += strlen(args + at) + 1) {
        word[words++] = args + at;
    }
    if (words < 5 || strcmp(word[0], "/bin/sh") != 0 || strcmp(word[1], "-c") != 0 || strcmp(word[4], file) != 0
        || (strcmp(word[3], "c300x-announce") != 0 && strcmp(word[3], "c300x-announce-off") != 0)) {
        return 0;
    }
    if (strcmp(word[3], "c300x-announce-off") == 0 && words == 7 && word[6][0] >= '0' && word[6][0] <= '9') {
        *gain = atoi(word[6]);
    }
    return 1;
}

int c300x_announce_end_leftover(int *gain)
{
    DIR *proc = opendir("/proc");
    struct dirent *entry;
    int found = 0;

    while (proc != NULL && (entry = readdir(proc)) != NULL) {
        pid_t pid = (pid_t)atoi(entry->d_name);
        if (pid > 1 && pid != getpid() && getpgid(pid) == pid && leftover(entry->d_name, c300x_announce_file(), gain)) {
            found = kill(-pid, SIGKILL) == 0 || found;
        }
    }
    if (proc != NULL) {
        closedir(proc);
    }
    return found;
}
