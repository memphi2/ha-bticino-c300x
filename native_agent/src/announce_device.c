#include "announce_device.h"
#include "announce_file.h"

#include <dirent.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define TOOLS \
    "A=${C300X_AMIXER:-/usr/bin/amixer}\n" \
    "S=${C300X_PCM_STATUS:-/proc/asound/card0/pcm0p/sub0/status}\n" \
    "put() { \"$A\" -q cset \"name='$1'\" \"$2\"; }\n" \
    "val() { \"$A\" cget \"name='$1'\" 2>/dev/null | sed -n 's/.*: values=//p'; }\n"

/* The device plays sound only in a sound state with the audio chip's
 * configuration for it loaded (to RAM, never saved), the speaker unmuted and
 * the amplifier on; the device's own software does the same for a voice
 * memo. The gain before is told to the agent. The script has no signal
 * handling: a stop or a door call ends its whole process group at once. */
const char C300X_ANNOUNCE_PLAY_SCRIPT[] =
    TOOLS
    "P=${C300X_APLAY:-/usr/bin/aplay}\n"
    "Z=${C300X_ZL_TOOL:-/bin/zl38005_ioctl-v2}\n"
    "C=${C300X_ZL_PLAY_CONFIG:-/home/bticino/microsemi/MEMO_AM_PLAY.cr}\n"
    "[ \"$(val Zia_Aud_St)\" = 0 ] && grep -q closed \"$S\" || exit 3\n"
    "echo \"gain=$(val 'ZL0 Rout Gain Volume')\"\n"
    "put Zia_Aud_St 9 || exit 4\n"
    "LD_LIBRARY_PATH=/home/bticino/lib \"$Z\" DOWNLOAD_CR \"$C\" NOT_SAVE NOT_FORCE >/dev/null 2>&1 || exit 4\n"
    "put 'ZL0 Mute Rout' off && put 'ZL0 Rout Gain Volume' \"$2\" && put 'TPA2028D1 Volume' 9 || exit 4\n"
    "\"$P\" -q -D plughw:0,0 -d \"$3\" \"$1\" || exit 5\n";

/* After every sound the speaker is muted, the amplifier off and the gain as
 * before. Not when the device's software has meanwhile switched to a state of
 * its own or plays itself: then the speaker is its. Its sound driver sets the
 * state to off by itself when a playing ends. */
const char C300X_ANNOUNCE_CLEAN_SCRIPT[] =
    TOOLS
    "sleep \"$1\"\n"
    "case \"$(val Zia_Aud_St)\" in 0|9) ;; *) exit 0;; esac\n"
    "grep -q closed \"$S\" || exit 0\n"
    "put 'ZL0 Mute Rout' on; put 'TPA2028D1 Volume' 0\n"
    "[ -z \"$2\" ] || put 'ZL0 Rout Gain Volume' \"$2\"\n"
    "[ \"$(val Zia_Aud_St)\" != 9 ] || put Zia_Aud_St 0\n"
    "exit 0\n";

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
