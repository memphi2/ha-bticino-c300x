#ifndef C300X_ANNOUNCE_DEVICE_H
#define C300X_ANNOUNCE_DEVICE_H

/* Arguments: sound file, speaker gain, seconds until aplay stops. */
extern const char C300X_ANNOUNCE_PLAY_SCRIPT[];
/* Arguments: seconds to wait first, the gain to set back or empty. */
extern const char C300X_ANNOUNCE_CLEAN_SCRIPT[];
/* Why the agent ended a sound itself. */
enum { C300X_ANNOUNCE_STOPPED = 6, C300X_ANNOUNCE_PREEMPTED = 7 };

/* The speaker gain the play script reported, or -1. */
int c300x_announce_read_gain(const char *output);
/* How a sound ended, from why the agent ended it and the play script's exit status. */
const char *c300x_announce_result_of(int ending, int status);
/* Ends the play script of an agent that was killed while it played; 1 if one was found. */
int c300x_announce_end_leftover(void);

#endif
