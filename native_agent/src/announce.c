#include "announce.h"
#include "announce_device.h"
#include "announce_file.h"
#include "device_detect.h"
#include "time_util.h"

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define STOPPED C300X_ANNOUNCE_STOPPED
#define PREEMPTED C300X_ANNOUNCE_PREEMPTED

/* Seconds the device's software gets to take the speaker after a door frame. */
#define PREEMPT_CLEAN_DELAY 3
/* After a stop the killed player has let go of the sound device. */
#define STOP_CLEAN_DELAY 1
/* The speaker stays the device's this long after a ring frame: its tone has pauses. */
#define RING_HOLD_SECONDS "60"
/* Well beyond the switching off's own 300 looks for an idle device, every two seconds. */
#define CLEAN_WAIT_SECONDS 1810

void c300x_announce_init(struct c300x_announce *announce)
{
    memset(announce, 0, sizeof(*announce));
    c300x_command_job_init(&announce->job);
    announce->clean_delay = -1;
    announce->gain = -1;
    announce->result = "";
    announce->ring_hold_ms = 1000LL * atoi(c300x_announce_path("C300X_ANNOUNCE_RING_HOLD", RING_HOLD_SECONDS));
}

void c300x_announce_take_over(struct c300x_announce *announce)
{
    /* A killed agent's sound that played to its end left its file and the speaker on. */
    int unplayed = access(c300x_announce_file(), F_OK) == 0;

    announce->serving = 1;
    /* This backend never owned C100X playback or its worker descendants. */
    if (c300x_device_model() == C300X_DEVICE_MODEL_C300X
        && (c300x_announce_end_leftover(&announce->gain) || unplayed)) {
        /* As after a door frame: what the old agent knew about the device is gone. */
        announce->ring_until_ms = c300x_monotonic_ms() + announce->ring_hold_ms;
        announce->door_hold = 1;
        announce->clean_delay = PREEMPT_CLEAN_DELAY;
    }
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

/* Why no new sound is taken now, or NULL. During a ring, and while the
 * switching off after a door frame waits for the device, the device has it. */
static const char *refusal(const struct c300x_announce *announce)
{
    if (announce->ring_until_ms > c300x_monotonic_ms()
        || (announce->door_hold && c300x_announce_busy(announce))) {
        return "device_busy";
    }
    return c300x_announce_busy(announce) ? "busy" : NULL;
}

int c300x_announce_write(const struct c300x_announce *announce, long offset,
    const unsigned char *data, size_t len, const char **error)
{
    *error = refusal(announce);
    return *error == NULL && c300x_announce_file_write(offset, data, len, error);
}

/* The switching off sleeps first until a ring's hold is over. */
static void start_clean(struct c300x_announce *announce)
{
    char delay_text[16], gain_text[16] = "";
    char *argv[] = {"/bin/sh", "-c", (char *)C300X_ANNOUNCE_CLEAN_SCRIPT, "c300x-announce-off",
        (char *)c300x_announce_file(), delay_text, gain_text, NULL};
    long long ring_left = announce->ring_until_ms - c300x_monotonic_ms();
    int delay = announce->clean_delay;

    /* Recovery bypasses the HTTP capability check. C100X has different
     * mixer controls and no compatible speaker backend yet. */
    if (c300x_device_model() != C300X_DEVICE_MODEL_C300X) {
        announce->clean_delay = -1;
        announce->gain = -1;
        return;
    }
    if (ring_left > 0 && ring_left / 1000 + 1 > delay) {
        delay = (int)(ring_left / 1000 + 1);
    }
    snprintf(delay_text, sizeof(delay_text), "%d", delay);
    if (announce->gain >= 0) {
        snprintf(gain_text, sizeof(gain_text), "%d", announce->gain);
    }
    announce->cleaning = c300x_command_job_start_wait(&announce->job, argv[0], argv,
        (delay + CLEAN_WAIT_SECONDS) * 1000);
    if (announce->cleaning) {
        announce->clean_delay = -1;
    }
}

int c300x_announce_play(struct c300x_announce *announce, int volume_percent,
    int *duration_ms, const char **error)
{
    *error = "unsupported";
    if (c300x_device_model() != C300X_DEVICE_MODEL_C300X) {
        return 0;
    }
    if ((*error = refusal(announce)) != NULL) {
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
    if (!c300x_announce_start_play(&announce->job, 21 + volume_percent * 53 / 100, *duration_ms / 1000 + 2,
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
        announce->door_hold = 1;
    }
}

int c300x_announce_prepare(const struct c300x_announce *announce, struct pollfd *fd)
{
    int timeout = c300x_command_job_prepare(&announce->job, fd);

    /* A switching off that could not start is tried again within a second. */
    return announce->job.pid == 0 && announce->clean_delay >= 0 ? 1000 : timeout;
}

/* The job has ended: the sound's result, then the switching off it needs. */
static void job_over(struct c300x_announce *announce, int cleaned, int ending)
{
    int exit_status = announce->job.exit_status;

    if (!cleaned) {
        int gain = c300x_announce_read_gain(announce->job.output);
        announce->gain = gain >= 0 ? gain : announce->gain;
        announce->result = c300x_announce_result_of(ending, announce->job.exit_status);
        (void)unlink(c300x_announce_file());
    }
    c300x_command_job_close(&announce->job);
    c300x_command_job_init(&announce->job);
    announce->cleaning = 0;
    announce->ending = 0;
    announce->door_hold = ending == PREEMPTED;
    /* Done, or nothing was switched because the device had its speaker in use.
     * A switching off that gave up waiting for the device starts again. */
    if ((cleaned && ending != PREEMPTED && exit_status == 0)
        || (!cleaned && strcmp(announce->result, "device_busy") == 0)) {
        /* A finished switching off has set the gain back: a later one leaves it alone. */
        announce->gain = cleaned ? -1 : announce->gain;
        return;
    }
    announce->clean_delay = ending == PREEMPTED ? PREEMPT_CLEAN_DELAY : ending == STOPPED ? STOP_CLEAN_DELAY : 0;
}

void c300x_announce_tick(struct c300x_announce *announce)
{
    int cleaned = announce->cleaning;
    int ending = announce->ending;

    if (announce->job.pid != 0) {
        c300x_command_job_tick(&announce->job);
        if (!announce->job.complete || announce->job.pid != 0) {
            return;
        }
        job_over(announce, cleaned, ending);
    }
    if (announce->clean_delay >= 0) {
        start_clean(announce);
    }
}

void c300x_announce_close(struct c300x_announce *announce)
{
    /* An agent that never had the API port leaves the sound and file of the one that has. */
    if (!announce->serving) {
        return;
    }
    /* A sound, or a switching off a door frame ended; one under way finishes on its own. */
    if (announce->job.pid > 0 && (!announce->cleaning || announce->ending == PREEMPTED)) {
        int cleaned = announce->cleaning;
        end_job(announce, STOPPED);
        for (int round = 0; round < 200 && announce->job.pid != 0; round++) {
            c300x_command_job_tick(&announce->job);
            if (announce->job.pid != 0) {
                (void)usleep(10000);
            }
        }
        job_over(announce, cleaned, announce->ending);
    }
    if (announce->job.pid == 0 && (announce->clean_delay >= 0
            || (announce->ring_until_ms > c300x_monotonic_ms() && c300x_announce_supported(announce)))) {
        /* It finishes on its own, or the next agent takes it over with a ring's hold. */
        announce->clean_delay = announce->clean_delay >= 0 ? announce->clean_delay : 0;
        start_clean(announce);
        announce->job.pid = 0;
    }
    (void)unlink(c300x_announce_file());
}
