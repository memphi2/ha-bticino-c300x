#ifndef C300X_ANNOUNCE_H
#define C300X_ANNOUNCE_H

#include "command_job.h"

/* About two minutes of 8 kHz mono sound. */
#define C300X_ANNOUNCE_MAX_BYTES (2 * 1024 * 1024)

struct c300x_announce {
    struct c300x_command_job job;
    int cleaning;
    const char *result;
};

void c300x_announce_init(struct c300x_announce *announce);
int c300x_announce_supported(void);
int c300x_announce_playing(const struct c300x_announce *announce);
/* One piece of the sound file in order; offset 0 starts a new file. */
int c300x_announce_write(const struct c300x_announce *announce, long offset,
    const unsigned char *data, size_t len, const char **error);
int c300x_announce_play(struct c300x_announce *announce, int volume_percent,
    int *duration_ms, const char **error);
void c300x_announce_stop(struct c300x_announce *announce);
/* A door call takes the speaker at once. */
void c300x_announce_preempt(struct c300x_announce *announce);
int c300x_announce_prepare(const struct c300x_announce *announce, struct pollfd *fd);
void c300x_announce_tick(struct c300x_announce *announce);
void c300x_announce_close(struct c300x_announce *announce);

#endif
