#include "announce.h"

#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

enum { PLAYED = 0, DEVICE_BUSY = 3, PATH_FAILED = 4, PLAY_FAILED = 5, STOPPED = 6, PREEMPTED = 7 };

/* The device plays sound only in a sound state with the audio chip's
 * configuration for it loaded (to RAM, never saved), the speaker unmuted and
 * the amplifier on; the device's own software does the same for a voice memo.
 * Its sound driver sets the state to off by itself when the playing ends.
 * Afterwards the speaker is muted and its gain is what it was, unless the device's software has
 * switched to a state of its own meanwhile. A door call (USR1) only frees the
 * sound device: the device's software is switching the speaker for the call
 * at that moment and nothing may be undone under it. If it had set its state
 * already, the driver's "off" would wipe it, so that state is set again.
 * Without a file only the speaker is switched off. */
static const char SCRIPT[] =
    "A=${C300X_AMIXER:-/usr/bin/amixer}; P=${C300X_APLAY:-/usr/bin/aplay}\n"
    "Z=${C300X_ZL_TOOL:-/bin/zl38005_ioctl-v2}\n"
    "C=${C300X_ZL_PLAY_CONFIG:-/home/bticino/microsemi/MEMO_AM_PLAY.cr}\n"
    "S=${C300X_PCM_STATUS:-/proc/asound/card0/pcm0p/sub0/status}\n"
    "K=; G=\n"
    "put() { \"$A\" -q cset \"name='$1'\" \"$2\"; }\n"
    "val() { \"$A\" cget \"name='$1'\" 2>/dev/null | sed -n 's/.*: values=//p'; }\n"
    "set_state() { put Zia_Aud_St \"$1\"; }\n"
    "st() { val Zia_Aud_St; }\n"
    "off() { put 'ZL0 Mute Rout' on; put 'TPA2028D1 Volume' 0;"
    " [ -z \"$G\" ] || put 'ZL0 Rout Gain Volume' \"$G\"; set_state 0; }\n"
    "fin() { [ -n \"$K\" ] && kill \"$K\" 2>/dev/null; wait;"
    " case \"$(st)\" in 0|9) off >/dev/null 2>&1;; esac; exit \"$1\"; }\n"
    "pre() { B=$(st); if [ -n \"$K\" ]; then kill \"$K\" 2>/dev/null; wait;"
    " case \"$B\" in 0|9) ;; *) set_state \"$B\";; esac;"
    " elif [ \"$B\" = 9 ]; then set_state 0; fi; exit 7; }\n"
    "[ -n \"$1\" ] || fin 0\n"
    "[ \"$(st)\" = 0 ] && grep -q closed \"$S\" || exit 3\n"
    "G=$(val 'ZL0 Rout Gain Volume')\n"
    "trap 'fin 6' TERM INT\n"
    "trap pre USR1\n"
    "set_state 9 || fin 4\n"
    "LD_LIBRARY_PATH=/home/bticino/lib \"$Z\" DOWNLOAD_CR \"$C\" NOT_SAVE NOT_FORCE >/dev/null 2>&1 || fin 4\n"
    "put 'ZL0 Mute Rout' off && put 'ZL0 Rout Gain Volume' \"$2\" && put 'TPA2028D1 Volume' 9 || fin 4\n"
    "\"$P\" -q -D plughw:0,0 -d \"$3\" \"$1\" & K=$!\n"
    "wait \"$K\"; R=$?; K=\n"
    "[ \"$R\" = 0 ] && fin 0\n"
    "fin 5\n";

static const char *path(const char *name, const char *fallback)
{
    const char *value = getenv(name);
    return value != NULL && value[0] != '\0' ? value : fallback;
}

static const char *sound_file(void)
{
    return path("C300X_ANNOUNCE_FILE", "/tmp/c300x-announce.wav");
}

void c300x_announce_init(struct c300x_announce *announce)
{
    memset(announce, 0, sizeof(*announce));
    c300x_command_job_init(&announce->job);
    announce->result = "";
}

int c300x_announce_supported(void)
{
    return access(path("C300X_AMIXER", "/usr/bin/amixer"), X_OK) == 0
        && access(path("C300X_APLAY", "/usr/bin/aplay"), X_OK) == 0
        && access(path("C300X_ZL_TOOL", "/bin/zl38005_ioctl-v2"), X_OK) == 0
        && access(path("C300X_ZL_PLAY_CONFIG", "/home/bticino/microsemi/MEMO_AM_PLAY.cr"), R_OK) == 0;
}

int c300x_announce_playing(const struct c300x_announce *announce)
{
    return announce->job.pid > 0;
}

int c300x_announce_write(const struct c300x_announce *announce, long offset,
    const unsigned char *data, size_t len, const char **error)
{
    struct stat info;
    int fd;
    int ok;

    *error = "busy";
    if (c300x_announce_playing(announce)) {
        return 0;
    }
    *error = "invalid_audio";
    if (offset < 0 || len == 0 || (size_t)offset + len > C300X_ANNOUNCE_MAX_BYTES) {
        return 0;
    }
    *error = "write_failed";
    /* Nothing another user put at this name is followed or written to. */
    if (offset == 0) {
        (void)unlink(sound_file());
    }
    fd = open(sound_file(), O_WRONLY | O_NOFOLLOW | O_CLOEXEC | (offset == 0 ? O_CREAT | O_EXCL : O_APPEND), 0600);
    if (fd < 0) {
        return 0;
    }
    ok = fstat(fd, &info) == 0 && S_ISREG(info.st_mode) && info.st_uid == geteuid();
    if (ok && info.st_size != offset) {
        *error = "invalid_audio";
        ok = 0;
    }
    ok = ok && write(fd, data, len) == (ssize_t)len;
    return close(fd) == 0 && ok;
}

static unsigned long le(const unsigned char *bytes, int count)
{
    unsigned long value = 0;
    while (count-- > 0) {
        value = (value << 8) | bytes[count];
    }
    return value;
}

/* The sound device takes only 8 kHz, 16 bit; anything else would play at the
 * wrong speed or not at all. */
static int wav_duration_ms(const char *file)
{
    unsigned char head[512];
    struct stat info;
    size_t used, at = 12;
    unsigned long channels = 0;
    int fd = open(file, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    ssize_t got;

    if (fd < 0) {
        return 0;
    }
    got = fstat(fd, &info) == 0 && S_ISREG(info.st_mode) ? read(fd, head, sizeof(head)) : -1;
    (void)close(fd);
    used = got > 0 ? (size_t)got : 0;
    if (used < 12 || memcmp(head, "RIFF", 4) != 0 || memcmp(head + 8, "WAVE", 4) != 0) {
        return 0;
    }
    while (at + 8 <= used) {
        unsigned long size = le(head + at + 4, 4);
        if (memcmp(head + at, "fmt ", 4) == 0) {
            if (size < 16 || at + 24 > used || le(head + at + 8, 2) != 1 || le(head + at + 12, 4) != 8000
                || le(head + at + 22, 2) != 16) {
                return 0;
            }
            channels = le(head + at + 10, 2);
        } else if (memcmp(head + at, "data", 4) == 0) {
            if (channels < 1 || channels > 2 || size == 0 || size > (unsigned long)info.st_size - at - 8) {
                return 0;
            }
            return (int)(size / (16 * channels)) + 1;
        }
        at += 8 + size + (size & 1);
    }
    return 0;
}

static int start(struct c300x_announce *announce, const char *file, int gain, int seconds, int timeout_ms)
{
    char gain_text[16], seconds_text[16];
    char *argv[] = {"/bin/sh", "-c", (char *)SCRIPT, "c300x-announce", (char *)file, gain_text, seconds_text, NULL};

    snprintf(gain_text, sizeof(gain_text), "%d", gain);
    snprintf(seconds_text, sizeof(seconds_text), "%d", seconds);
    return c300x_command_job_start_wait(&announce->job, argv[0], argv, timeout_ms);
}

int c300x_announce_play(struct c300x_announce *announce, int volume_percent,
    int *duration_ms, const char **error)
{
    *error = "busy";
    if (c300x_announce_playing(announce)) {
        return 0;
    }
    *error = "invalid_volume";
    if (volume_percent < 1 || volume_percent > 100) {
        return 0;
    }
    *error = "invalid_audio";
    *duration_ms = wav_duration_ms(sound_file());
    if (*duration_ms <= 0) {
        return 0;
    }
    *error = "start_failed";
    announce->cleaning = 0;
    /* The device's own table for playing: speaker gain 26 at 10 % up to 74 at 100 %. */
    if (!start(announce, sound_file(), 21 + volume_percent * 53 / 100, *duration_ms / 1000 + 2,
            *duration_ms + 30000)) {
        return 0;
    }
    announce->result = "";
    return 1;
}

void c300x_announce_stop(struct c300x_announce *announce)
{
    if (c300x_announce_playing(announce) && !announce->cleaning) {
        (void)kill(announce->job.pid, SIGTERM);
    }
}

void c300x_announce_preempt(struct c300x_announce *announce)
{
    if (c300x_announce_playing(announce) && !announce->cleaning) {
        (void)kill(announce->job.pid, SIGUSR1);
    }
}

int c300x_announce_prepare(const struct c300x_announce *announce, struct pollfd *fd)
{
    return c300x_command_job_prepare(&announce->job, fd);
}

void c300x_announce_tick(struct c300x_announce *announce)
{
    int status, cleaned = announce->cleaning;

    c300x_command_job_tick(&announce->job);
    if (!announce->job.complete || announce->job.pid != 0) {
        return;
    }
    status = announce->job.exit_status;
    c300x_command_job_close(&announce->job);
    c300x_command_job_init(&announce->job);
    announce->cleaning = 0;
    (void)unlink(sound_file());
    if (cleaned) {
        return;
    }
    announce->result = status == PLAYED ? "played" : status == DEVICE_BUSY ? "device_busy"
        : status == PATH_FAILED ? "sound_path_failed" : status == PLAY_FAILED ? "play_failed"
        : status == STOPPED ? "stopped" : status == PREEMPTED ? "preempted" : "failed";
    /* Killed or timed out: the speaker may still be on. */
    if (strcmp(announce->result, "failed") == 0) {
        announce->cleaning = start(announce, "", 0, 0, 10000);
    }
}

void c300x_announce_close(struct c300x_announce *announce)
{
    c300x_announce_stop(announce);
}
