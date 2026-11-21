#include "announce.h"
#include "announce_device.h"
#include "announce_file.h"
#include "time_util.h"

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

enum { PLAYED = 0, DEVICE_BUSY = 3, PATH_FAILED = 4, PLAY_FAILED = 5, STOPPED = 6, PREEMPTED = 7 };

/* Seconds the device's software gets to take the speaker after a door call
 * frame before the speaker is switched off. */
#define PREEMPT_CLEAN_DELAY 3
/* After a stop the killed player has let go of the sound device. */
#define STOP_CLEAN_DELAY 1
/* A ring whose end frame was lost no longer counts after this. */
#define CALL_MS (180 * 1000)

void c300x_announce_init(struct c300x_announce *announce)
{
    memset(announce, 0, sizeof(*announce));
    c300x_command_job_init(&announce->job);
    announce->clean_delay = -1;
    announce->gain = -1;
    announce->result = "";
    if (c300x_announce_end_leftover()) {
        announce->clean_delay = STOP_CLEAN_DELAY;
    }
    /* A file from before a restart is never played. */
    (void)unlink(c300x_announce_file());
}

/* From a ring to the end of its call the speaker is the device's, also in pauses. */
static int door_call(const struct c300x_announce *announce)
{
    return announce->call_until_ms > c300x_monotonic_ms();
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
    char *argv[] = {"/bin/sh", "-c", (char *)C300X_ANNOUNCE_PLAY_SCRIPT, "c300x-announce", (char *)c300x_announce_file(),
        gain_text, seconds_text, NULL};

    snprintf(gain_text, sizeof(gain_text), "%d", gain);
    snprintf(seconds_text, sizeof(seconds_text), "%d", seconds);
    return c300x_command_job_start_output(&announce->job, argv[0], argv, timeout_ms);
}

static void start_clean(struct c300x_announce *announce)
{
    char delay_text[16], gain_text[16] = "";
    char *argv[] = {"/bin/sh", "-c", (char *)C300X_ANNOUNCE_CLEAN_SCRIPT, "c300x-announce-off", delay_text, gain_text, NULL};

    if (door_call(announce)) {
        return;
    }
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
    *error = "device_busy";
    if (door_call(announce)) {
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
        /* A stop does not turn a door call into a plain stop. */
        announce->ending = announce->ending == PREEMPTED ? PREEMPTED : why;
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

void c300x_announce_door_frame(struct c300x_announce *announce, const char *frame)
{
    if (strncmp(frame, "*8*1#1#", 7) == 0) {
        announce->call_until_ms = c300x_monotonic_ms() + CALL_MS;
    } else if (strncmp(frame, "*8*3#", 5) == 0) {
        announce->call_until_ms = 0;
    }
    if (c300x_announce_frame_takes_speaker(frame)) {
        c300x_announce_preempt(announce);
    }
}

int c300x_announce_prepare(const struct c300x_announce *announce, struct pollfd *fd)
{
    int timeout = c300x_command_job_prepare(&announce->job, fd);

    /* A switching off that is still due is tried again within a second. */
    return announce->job.pid == 0 && announce->clean_delay >= 0 ? 1000 : timeout;
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
    announce->clean_delay = ending == PREEMPTED ? PREEMPT_CLEAN_DELAY : ending == STOPPED ? STOP_CLEAN_DELAY : 0;
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
        announce->clean_delay = STOP_CLEAN_DELAY;
    }
    if (announce->job.pid == 0 && announce->clean_delay >= 0) {
        /* It finishes on its own after the agent has ended. */
        start_clean(announce);
        announce->job.pid = 0;
    }
    (void)unlink(c300x_announce_file());
}
