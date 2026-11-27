#ifndef C300X_AUDIO_LEVEL_H
#define C300X_AUDIO_LEVEL_H

#include <stddef.h>
#include <stdint.h>

/* The two level settings for the door station's sound toward Home
 * Assistant, the same on every station and codec:
 * door level: stock, +3, +6, +9 or +12 dB; in the audio chip where the
 *   station has the lever, else the same dB in software;
 * fine adjustment: -10..+10 dB, always in software.
 * The software stage applies fine + door level - what the chip adds right
 * now, so the result is the same whichever path carries the door level. */
#define C300X_DOOR_LEVEL_MAX_DB 12
#define C300X_DOOR_LEVEL_STEP_DB 3
#define C300X_FINE_GAIN_MIN_DB (-10)
#define C300X_FINE_GAIN_MAX_DB 10
#define C300X_AUDIO_LEVEL_JSON_MAX 192

int c300x_audio_level_valid(int door_level_db, int fine_gain_db);
/* Stores both and moves the door level into the chip or out of it. A chip
 * that cannot take it is no error: the software stage carries it then. */
int c300x_audio_level_set(int door_level_db, int fine_gain_db);
/* {"door_level_db":..,"fine_gain_db":..,"door_level_path":..,"chip_lever":..,
 *  "chip_gain_db":..,"software_gain_db":..} */
size_t c300x_audio_level_json(char *out, size_t out_len);
/* Per audio packet toward Home Assistant: PCMU in place, or linear samples
 * encoded to PCMU. apply 0 leaves the level alone (calls with the home). */
void c300x_audio_level_pcmu(unsigned char *data, size_t len, int apply);
void c300x_audio_level_to_pcmu(const int16_t *samples, unsigned char *out, size_t count, int apply);
/* A doorbell media session with the door level starts or ends: the next
 * packet reads the chip at once and starts the frequent reads. */
void c300x_audio_level_session_boundary(void);
int c300x_audio_level_remove_patches(char *error, size_t error_len);

#endif
