#ifndef C300X_AUDIO_CODEC_H
#define C300X_AUDIO_CODEC_H

#include <stddef.h>

#include "c300x_agent.h"

/*
 * Native, in-binary switch of the on-demand/intercom audio codec between
 * speex (stock) and PCMU. It patches two device config files in lock-step —
 * stack_open.xml (<enable_speex>) and linphone.conf ([sound] rtp_map/rtp_ptnum
 * + [audio_codec_*] enabled) — because they must agree or the device emits
 * speex bytes labelled as PCMU. Originals are backed up once (under the rw
 * cfg/extra partition) and restore copies them back; both files live on the
 * read-only rootfs so writes are wrapped in a rw remount. A codec change only
 * takes effect after the device reboots.
 *
 * This lives in the agent binary (an already-deployed, allowlisted file) so it
 * needs no new bundle file — an older agent's auto-update allowlist rejects
 * unknown filenames, which would break the update.
 */

#define C300X_AUDIO_CODEC_STATE_LEN 16

struct c300x_audio_codec_status {
    int supported;        /* both target files exist */
    int backup_present;   /* both originals are backed up */
    int changed;          /* last apply/restore actually wrote device files */
    char state[C300X_AUDIO_CODEC_STATE_LEN]; /* "speex" | "pcmu" | "partial" */
    char error[C300X_MAX_ERROR_LEN];
};

/* Runtime codec mode, derived from the device itself (stack_open.xml
 * enable_speex) rather than agent config: 1 = the device emits PCMU, 0 = speex.
 * bt_av_media reads the same flag at boot, so an agent that reads it at startup
 * always matches the device — no separate config value that could drift. */
int c300x_audio_codec_device_is_pcmu(void);

int c300x_audio_codec_read_status(struct c300x_audio_codec_status *status);
int c300x_audio_codec_reboot_required(
    const struct c300x_audio_codec_status *status,
    const char *running_state
);
void c300x_audio_codec_status_body(
    const struct c300x_audio_codec_status *status,
    const char *running_state,
    char *body,
    size_t body_len
);
void c300x_audio_codec_action_body(
    const struct c300x_audio_codec_status *status,
    const char *running_state,
    int rebooting,
    char *body,
    size_t body_len
);
int c300x_audio_codec_apply(
    struct c300x_audio_codec_status *status,
    char *error,
    size_t error_len
);
int c300x_audio_codec_restore(
    struct c300x_audio_codec_status *status,
    char *error,
    size_t error_len
);

#endif
