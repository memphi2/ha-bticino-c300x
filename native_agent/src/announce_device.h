#ifndef C300X_ANNOUNCE_DEVICE_H
#define C300X_ANNOUNCE_DEVICE_H

/* Arguments: sound file, speaker gain, seconds until aplay stops. */
extern const char C300X_ANNOUNCE_PLAY_SCRIPT[];
/* Arguments: seconds to wait first, the gain to set back or empty. */
extern const char C300X_ANNOUNCE_CLEAN_SCRIPT[];
/* Ends the play script of an agent that was killed while it played; 1 if one was found. */
int c300x_announce_end_leftover(void);

#endif
