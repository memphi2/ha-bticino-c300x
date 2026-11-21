#include "announce.h"
#include "announce_file.h"

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

enum { PLAYED = 0, DEVICE_BUSY = 3, PATH_FAILED = 4, PLAY_FAILED = 5, STOPPED = 6, PREEMPTED = 7 };

/* Seconds the device's software gets to take the speaker after a door call
 * frame before the speaker is switched off. */
#define PREEMPT_CLEAN_DELAY 3

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
static const char PLAY_SCRIPT[] =
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
static const char CLEAN_SCRIPT[] =
    TOOLS
    "sleep \"$1\"\n"
    "case \"$(val Zia_Aud_St)\" in 0|9) ;; *) exit 0;; esac\n"
    "grep -q closed \"$S\" || exit 0\n"
    "put 'ZL0 Mute Rout' on; put 'TPA2028D1 Volume' 0\n"
    "[ -z \"$2\" ] || put 'ZL0 Rout Gain Volume' \"$2\"\n"
    "[ \"$(val Zia_Aud_St)\" != 9 ] || put Zia_Aud_St 0\n"
    "exit 0\n";

void c300x_announce_init(struct c300x_announce *announce)
{
    memset(announce, 0, sizeof(*announce));
    c300x_command_job_init(&announce->job);
    announce->clean_delay = -1;
    announce->gain = -1;
    announce->result = "";
    /* A file from before a restart is never played. */
    (void)unlink(c300x_announce_file());
}

int c300x_announce_playing(const struct c300x_announce *announce)
{
    return announce->job.pid > 0 && !announce->cleaning;
}

int c300x_announce_busy(const struct c300x_announce *announce)
{
    return announce->job.pid > 0 || announce->clean_delay >= 0;
}

int c300x_announce_write(const struct c300x_announce *announce, long offset,
    const unsigned char *data, size_t len, const char **error)
{
    *error = "busy";
    return !c300x_announce_busy(announce) && c300x_announce_file_write(offset, data, len, error);
}

static int start_play(struct c300x_announce *announce, int gain, int seconds, int timeout_ms)
{
    char gain_text[16], seconds_text[16];
    char *argv[] = {"/bin/sh", "-c", (char *)PLAY_SCRIPT, "c300x-announce", (char *)c300x_announce_file(),
        gain_text, seconds_text, NULL};

    snprintf(gain_text, sizeof(gain_text), "%d", gain);
    snprintf(seconds_text, sizeof(seconds_text), "%d", seconds);
    return c300x_command_job_start_output(&announce->job, argv[0], argv, timeout_ms);
}

static void start_clean(struct c300x_announce *announce)
{
    char delay_text[16], gain_text[16] = "";
    char *argv[] = {"/bin/sh", "-c", (char *)CLEAN_SCRIPT, "c300x-announce-off", delay_text, gain_text, NULL};

    snprintf(delay_text, sizeof(delay_text), "%d", announce->clean_delay);
    if (announce->gain >= 0) {
        snprintf(gain_text, sizeof(gain_text), "%d", announce->gain);
    }
    announce->cleaning = c300x_command_job_start_wait(&announce->job, argv[0], argv,
        (announce->clean_delay + 10) * 1000);
    if (announce->cleaning) {
        announce->clean_delay = -1;
    }
}

int c300x_announce_play(struct c300x_announce *announce, int volume_percent,
    int *duration_ms, const char **error)
{
    *error = "busy";
    if (c300x_announce_busy(announce)) {
        return 0;
    }
    *error = "invalid_volume";
    if (volume_percent < 1 || volume_percent > 100) {
        return 0;
    }
    *error = "invalid_audio";
    *duration_ms = c300x_announce_file_duration_ms(c300x_announce_file());
    if (*duration_ms <= 0) {
        return 0;
    }
    *error = "start_failed";
    announce->ending = 0;
    announce->gain = -1;
    /* The device's own table for playing: speaker gain 26 at 10 % up to 74 at 100 %. */
    if (!start_play(announce, 21 + volume_percent * 53 / 100, *duration_ms / 1000 + 2,
            *duration_ms + 30000)) {
        return 0;
    }
    announce->result = "";
    return 1;
}

/* The whole process group: the shell and the player end at the same moment. */
static void end_job(struct c300x_announce *announce, int why)
{
    if (announce->job.pid > 0) {
        announce->ending = why;
        (void)kill(-announce->job.pid, SIGKILL);
    }
}

void c300x_announce_stop(struct c300x_announce *announce)
{
    if (c300x_announce_playing(announce)) {
        end_job(announce, STOPPED);
    }
}

void c300x_announce_preempt(struct c300x_announce *announce)
{
    if (announce->job.pid > 0) {
        /* Also a switching off already under way: it starts again later. */
        end_job(announce, PREEMPTED);
    } else if (announce->clean_delay >= 0) {
        announce->clean_delay = PREEMPT_CLEAN_DELAY;
    }
}

int c300x_announce_prepare(const struct c300x_announce *announce, struct pollfd *fd)
{
    return c300x_command_job_prepare(&announce->job, fd);
}

static void read_gain(struct c300x_announce *announce)
{
    const char *line = strstr(announce->job.output, "gain=");
    char *end;
    long gain;

    if (line == NULL) {
        return;
    }
    gain = strtol(line + 5, &end, 10);
    if (end != line + 5 && (*end == '\n' || *end == '\0') && gain >= 0 && gain <= 255) {
        announce->gain = (int)gain;
    }
}

static const char *result_of(int ending, int status)
{
    if (ending == PREEMPTED || ending == STOPPED) {
        return ending == PREEMPTED ? "preempted" : "stopped";
    }
    return status == PLAYED ? "played" : status == DEVICE_BUSY ? "device_busy"
        : status == PATH_FAILED ? "sound_path_failed" : status == PLAY_FAILED ? "play_failed" : "failed";
}

void c300x_announce_tick(struct c300x_announce *announce)
{
    int cleaned = announce->cleaning;
    int ending = announce->ending;

    if (announce->job.pid == 0) {
        /* A switching off that could not start is tried again. */
        if (announce->clean_delay >= 0) {
            start_clean(announce);
        }
        return;
    }
    c300x_command_job_tick(&announce->job);
    if (!announce->job.complete || announce->job.pid != 0) {
        return;
    }
    if (!cleaned) {
        read_gain(announce);
        announce->result = result_of(ending, announce->job.exit_status);
        (void)unlink(c300x_announce_file());
    }
    c300x_command_job_close(&announce->job);
    c300x_command_job_init(&announce->job);
    announce->cleaning = 0;
    announce->ending = 0;
    if (cleaned && ending != PREEMPTED) {
        return;
    }
    /* Nothing was switched when the device had its speaker in use. */
    if (!cleaned && strcmp(announce->result, "device_busy") == 0) {
        return;
    }
    announce->clean_delay = ending == PREEMPTED ? PREEMPT_CLEAN_DELAY : 0;
    start_clean(announce);
}

void c300x_announce_close(struct c300x_announce *announce)
{
    if (c300x_announce_playing(announce)) {
        end_job(announce, STOPPED);
        /* The killed script is reaped and its output read for the gain. */
        for (int round = 0; round < 200 && announce->job.pid != 0; round++) {
            c300x_command_job_tick(&announce->job);
            if (announce->job.pid != 0) {
                (void)usleep(10000);
            }
        }
        read_gain(announce);
        c300x_command_job_close(&announce->job);
        c300x_command_job_init(&announce->job);
        announce->clean_delay = 0;
        /* It finishes on its own after the agent has ended. */
        start_clean(announce);
        announce->job.pid = 0;
    }
    (void)unlink(c300x_announce_file());
}
