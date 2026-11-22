/* Link-time HTTP lab substitutes: no codec file or mount operation runs. */
#include "../src/audio_codec.h"
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int __wrap_c300x_audio_codec_read_status(struct c300x_audio_codec_status *status)
{
    memset(status, 0, sizeof(*status));
    status->supported = 1;
    snprintf(status->state, sizeof(status->state), "speex");
    return 1;
}

static int mutation(struct c300x_audio_codec_status *status, char *error, size_t size,
    const char *state)
{
    __wrap_c300x_audio_codec_read_status(status);
    if (access("codec-fail", F_OK) == 0) {
        snprintf(error, size, "simulated codec failure");
        return 0;
    }
    snprintf(status->state, sizeof(status->state), "%s", state);
    status->changed = access("codec-unchanged", F_OK) != 0;
    status->backup_present = 1;
    return 1;
}

int __wrap_c300x_audio_codec_apply(struct c300x_audio_codec_status *status, char *error, size_t size)
{
    return mutation(status, error, size, "pcmu");
}

int __wrap_c300x_audio_codec_restore(struct c300x_audio_codec_status *status, char *error, size_t size)
{
    return mutation(status, error, size, "speex");
}
