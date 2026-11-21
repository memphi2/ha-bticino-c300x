#include "announce_device.h"
#include "announce.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TOOLS \
    "A=${C300X_AMIXER:-/usr/bin/amixer}\n" \
    "S=${C300X_PCM_STATUS:-/proc/asound/card0/pcm0p/sub0/status}\n" \
    "put() { \"$A\" -q cset \"name='$1'\" \"$2\"; }\n" \
    "val() { \"$A\" cget \"name='$1'\" 2>/dev/null | sed -n 's/.*: values=//p'; }\n"

/* The device plays sound only in a sound state with the audio chip's
 * configuration for it loaded (to RAM, never saved), the speaker unmuted and
 * the amplifier on; the device's own software does the same for a voice
 * memo. The gain before, and that the speaker is on, are told to the agent. The script has no signal
 * handling: a stop or a door call ends its whole process group at once. */
const char C300X_ANNOUNCE_PLAY_SCRIPT[] =
    TOOLS
    "P=${C300X_APLAY:-/usr/bin/aplay}\n"
    "Z=${C300X_ZL_TOOL:-/bin/zl38005_ioctl-v2}\n"
    "C=${C300X_ZL_PLAY_CONFIG:-/home/bticino/microsemi/MEMO_AM_PLAY.cr}\n"
    "case \"$(val Zia_Aud_St)\" in 0|9) grep -q closed \"$S\" || exit 3;; *) exit 3;; esac\n"
    "echo \"gain=$(val 'ZL0 Rout Gain Volume')\"\n"
    "put Zia_Aud_St 9 || exit 4\n"
    "LD_LIBRARY_PATH=/home/bticino/lib \"$Z\" DOWNLOAD_CR \"$C\" NOT_SAVE NOT_FORCE >/dev/null 2>&1 || exit 4\n"
    "put 'ZL0 Mute Rout' off && put 'ZL0 Rout Gain Volume' \"$2\" && put 'TPA2028D1 Volume' 9 || exit 4\n"
    "echo speaker=on\n"
    "\"$P\" -q -D plughw:0,0 -d \"$3\" \"$1\" || exit 5\n";

/* After every sound the speaker is muted, the amplifier off and the gain as
 * before. While the device's software has a state of its own or plays itself,
 * the speaker is its: switching off waits until the device is idle again, at
 * most ten minutes. Its sound driver sets the state to off by itself when a
 * playing ends. */
const char C300X_ANNOUNCE_CLEAN_SCRIPT[] =
    TOOLS
    "sleep \"$2\"\n"
    "n=0\n"
    "until case \"$(val Zia_Aud_St)\" in 0|9) grep -q closed \"$S\";; *) false;; esac; do\n"
    "n=$((n + 1)); [ \"$n\" -lt 300 ] || exit 0; sleep \"${C300X_ANNOUNCE_IDLE_POLL:-2}\"\n"
    "done\n"
    "put 'ZL0 Mute Rout' on; put 'TPA2028D1 Volume' 0\n"
    "[ -z \"$3\" ] || put 'ZL0 Rout Gain Volume' \"$3\"\n"
    "[ \"$(val Zia_Aud_St)\" != 9 ] || put Zia_Aud_St 0\n"
    "exit 0\n";

int c300x_announce_read_gain(const char *output)
{
    const char *line = strstr(output, "gain=");
    char *end;
    long gain;

    if (line == NULL) {
        return -1;
    }
    gain = strtol(line + 5, &end, 10);
    return end != line + 5 && (*end == '\n' || *end == '\0') && gain >= 0 && gain <= 255 ? (int)gain : -1;
}

const char *c300x_announce_result_of(int ending, int status)
{
    if (ending == C300X_ANNOUNCE_PREEMPTED || ending == C300X_ANNOUNCE_STOPPED) {
        return ending == C300X_ANNOUNCE_PREEMPTED ? "preempted" : "stopped";
    }
    return status == 0 ? "played" : status == 3 ? "device_busy" : status == 4 ? "sound_path_failed"
        : status == 5 ? "play_failed" : "failed";
}

/* The device let the agent have its speaker and the play script switched it on. */
int c300x_announce_started(const struct c300x_announce *announce)
{
    return c300x_announce_playing(announce) && strstr(announce->job.output, "speaker=on") != NULL;
}

#define JSON_BOOL(value) ((value) ? "true" : "false")

void c300x_announce_status_json(const struct c300x_announce *announce, int duration_ms, char *body, size_t size)
{
    snprintf(body, size,
        "{\"ok\":true,\"supported\":%s,\"playing\":%s,\"started\":%s,\"busy\":%s,\"result\":\"%s\","
        "\"duration_ms\":%d,\"max_bytes\":%d}\n",
        JSON_BOOL(c300x_announce_supported(announce)), JSON_BOOL(c300x_announce_playing(announce)),
        JSON_BOOL(c300x_announce_started(announce)), JSON_BOOL(c300x_announce_busy(announce)),
        announce->result, duration_ms, C300X_ANNOUNCE_MAX_BYTES);
}
