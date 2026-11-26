#ifndef C300X_AUDIO_CHIP_H
#define C300X_AUDIO_CHIP_H

#include <stddef.h>

/* The door level in the Classe 300X audio chip (ZL38005). The vendor HAL
 * loads IP_PE.cr for the audio toward the app or Home Assistant
 * (EN_AUDIO_IP_EU), sets 'ZL0 Sout Gain Volume' to 11 with it and then runs
 * /home/root/demo/Audio_State.sh, an empty stub on 1.7.19, 2.0.2 and 3.0.6.
 * Our version of that hook raises the gain by 3 dB a step in that state and
 * puts the profile's 11 back when the HAL goes on to a state without a
 * profile of its own (EN_AUDIO_OFF, EN_AUDIO_IP_IU); every other state loads
 * its own profile. The level lives in the hook itself, so a change rewrites
 * that one file; stock puts the vendor stub back. */
#define C300X_AUDIO_CHIP_STOCK_SOUT 11
#define C300X_AUDIO_CHIP_MAX_SOUT 15
#define C300X_AUDIO_CHIP_DB_PER_STEP 3
#define C300X_AUDIO_CHIP_MAX_STEPS 4

enum c300x_audio_hook_state {
    C300X_AUDIO_HOOK_MISSING = 0,
    C300X_AUDIO_HOOK_STOCK,
    C300X_AUDIO_HOOK_OURS,
    C300X_AUDIO_HOOK_FOREIGN,
};

/* The hook as it is on the device; *steps is the level of ours, else 0. */
enum c300x_audio_hook_state c300x_audio_chip_hook_state(int *steps);
/* The station can take the level in its chip: a C300X with the known
 * IP_PE.cr, amixer and a readable gain control. */
int c300x_audio_chip_supported(void);
/* steps 1..4 writes our hook (the stock stub backed up once), 0 restores
 * the stub and the gain a raised call may have left. */
int c300x_audio_chip_apply(int steps, char *error, size_t error_len);
int c300x_audio_chip_remove_patches(char *error, size_t error_len);
/* How many dB the chip adds right now: only while our hook has raised it in
 * the current audio state (its tmpfs mark), from the control's live value. */
int c300x_audio_chip_current_db(int *db);
size_t c300x_audio_chip_render_hook(int steps, char *out, size_t out_len);

#endif
