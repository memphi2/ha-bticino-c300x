#ifndef C300X_ANNOUNCE_H
#define C300X_ANNOUNCE_H

#include "command_job.h"

/* About two minutes of 8 kHz mono sound. */
#define C300X_ANNOUNCE_MAX_BYTES (2 * 1024 * 1024)

struct c300x_announce {
    struct c300x_command_job job;
    int cleaning;      /* the job switches the speaker off */
    int ending;        /* why the agent ended the sound, 0 if it did not */
    int clean_delay;   /* seconds; -1 while no switching off is due */
    int gain;          /* speaker gain before the sound, -1 if unknown */
    int door_events;   /* the agent hears door calls and can give way to them */
    long long ring_until_ms; /* the speaker is left to the device after a ring */
    long long ring_hold_ms;
    int door_hold;     /* the switching off follows a door frame */
    const char *result;
};

void c300x_announce_init(struct c300x_announce *announce);
int c300x_announce_supported(const struct c300x_announce *announce);
/* A sound plays; switching the speaker off afterwards is not part of it. */
int c300x_announce_playing(const struct c300x_announce *announce);
/* The device let the agent have its speaker for the sound that plays. */
int c300x_announce_started(const struct c300x_announce *announce);
/* Playing, or switching the speaker off: nothing new is taken. */
int c300x_announce_busy(const struct c300x_announce *announce);
/* One piece of the sound file in order; offset 0 starts a new file. */
int c300x_announce_write(const struct c300x_announce *announce, long offset,
    const unsigned char *data, size_t len, const char **error);
int c300x_announce_play(struct c300x_announce *announce, int volume_percent,
    int *duration_ms, const char **error);
void c300x_announce_stop(struct c300x_announce *announce);
/* A frame of the door entry bus after which the device takes its speaker. */
int c300x_announce_frame_takes_speaker(const char *frame);
/* Every frame of the door entry bus: a door call ends a sound, a ring holds off new ones. */
void c300x_announce_door_frame(struct c300x_announce *announce, const char *frame);
/* A door call takes the speaker at once. */
void c300x_announce_preempt(struct c300x_announce *announce);
int c300x_announce_prepare(const struct c300x_announce *announce, struct pollfd *fd);
void c300x_announce_tick(struct c300x_announce *announce);
void c300x_announce_close(struct c300x_announce *announce);
/* Plain base64 only: the shared decoder stops at some characters. */
int c300x_announce_plain_base64(const char *text);

#endif
