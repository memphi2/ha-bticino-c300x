#ifndef C300X_ANNOUNCE_FILE_H
#define C300X_ANNOUNCE_FILE_H

#include <stddef.h>

/* An environment value, or the fallback where it is not set. */
const char *c300x_announce_path(const char *name, const char *fallback);
/* Where the sound file is kept until it has played. */
const char *c300x_announce_file(void);
/* One piece of the sound file in order; offset 0 starts a new file. */
int c300x_announce_file_write(long offset, const unsigned char *data, size_t len, const char **error);
/* The length of a WAV the device can play, or 0. */
int c300x_announce_file_duration_ms(const char *file);

#endif
