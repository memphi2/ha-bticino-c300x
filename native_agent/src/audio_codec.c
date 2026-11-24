#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#include "audio_codec.h"
#include "device_detect.h"
#include "device_file.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <sys/stat.h>
#include <unistd.h>

/* Paths default to the real device locations but are env-overridable so the
 * logic can be exercised offline against synthetic fixtures. */
static const char *stack_open_path(void) {
    const char *p = getenv("C300X_AUDIO_STACK_OPEN");
    return (p != NULL && p[0] != '\0') ? p : "/home/bticino/cfg/stack_open.xml";
}

static const char *linphone_path(void) {
    const char *p = getenv("C300X_AUDIO_LINPHONE_CONF");
    return (p != NULL && p[0] != '\0') ? p : "/etc/linphone.conf";
}


static void set_err(char *error, size_t error_len, const char *message) {
    if (error != NULL && error_len > 0) {
        snprintf(error, error_len, "%s", message);
    }
}


static int contains(const char *data, const char *needle) {
    return data != NULL && strstr(data, needle) != NULL;
}

static int file_has(const char *path, const char *needle) {
    char *data = NULL;
    size_t len = 0;
    int hit;
    if (!c300x_device_file_read(path, &data, &len, NULL)) {
        return 0;
    }
    hit = contains(data, needle);
    free(data);
    return hit;
}

static int stack_open_has(const char *needle) {
    return file_has(stack_open_path(), needle);
}

static void read_linphone_facts(const char *path, int *is_pcmu, int *is_speex);

int c300x_audio_codec_device_is_pcmu(void) {
    /* Require BOTH files to agree on PCMU (stack_open enable_speex=0 AND a
     * consistent linphone.conf), matching read_status. A stack-only check would
     * commit the media bridge to PCMU on a half-applied/legacy config where
     * linphone still negotiates speex -> garbled audio. */
    int lin_pcmu = 0;
    int lin_speex = 0;
    if (!stack_open_has("<enable_speex>0</enable_speex>")) {
        return 0;
    }
    read_linphone_facts(linphone_path(), &lin_pcmu, &lin_speex);
    return lin_pcmu;
}

/* Parse linphone.conf once into two consistency verdicts. A fully-PCMU config
 * needs [sound] rtp_map=PCMU AND the PCMU codec enabled AND speex/8000
 * disabled; fully-speex is the mirror. Anything else is neither, so the
 * caller reports "partial" — this catches half-applied states the old
 * rtp_map-only check missed. Line-based, mirrors patch_linphone's section walk. */
static void read_linphone_facts(const char *path, int *is_pcmu, int *is_speex) {
    char *data = NULL;
    size_t len = 0;
    size_t i = 0;
    int sound_map = 0;      /* 0 none, 1 PCMU, 2 speex */
    int pcmu_enabled = -1;  /* -1 unknown, else 0/1 */
    int speex8_enabled = -1;
    char section[64] = "";
    char mime[32] = "";
    char rate[16] = "";

    *is_pcmu = 0;
    *is_speex = 0;
    if (!c300x_device_file_read(path, &data, &len, NULL)) {
        return;
    }
    while (i < len) {
        size_t j = i;
        size_t line_len;
        char line[512];
        while (j < len && data[j] != '\n') {
            j++;
        }
        line_len = j - i;
        if (line_len < sizeof(line)) {
            memcpy(line, data + i, line_len);
            line[line_len] = '\0';
            if (line[0] == '[') {
                snprintf(section, sizeof(section), "%.63s", line);
                mime[0] = '\0';
                rate[0] = '\0';
            } else if (strcmp(section, "[sound]") == 0
                       && strncmp(line, "rtp_map=", 8) == 0) {
                if (strcmp(line + 8, "PCMU/8000/1") == 0) {
                    sound_map = 1;
                } else if (strncmp(line + 8, "speex/8000", 10) == 0) {
                    sound_map = 2;
                }
            } else if (strncmp(section, "[audio_codec_", 13) == 0) {
                if (strncmp(line, "mime=", 5) == 0) {
                    snprintf(mime, sizeof(mime), "%.31s", line + 5);
                } else if (strncmp(line, "rate=", 5) == 0) {
                    snprintf(rate, sizeof(rate), "%.15s", line + 5);
                } else if (strncmp(line, "enabled=", 8) == 0) {
                    int value = strcmp(line + 8, "1") == 0;
                    if (strcmp(mime, "PCMU") == 0) {
                        pcmu_enabled = value;
                    } else if (strcmp(mime, "speex") == 0
                               && strcmp(rate, "8000") == 0) {
                        speex8_enabled = value;
                    }
                }
            }
        }
        i = (j < len) ? j + 1 : j;
    }
    free(data);
    *is_pcmu = (sound_map == 1 && pcmu_enabled == 1 && speex8_enabled == 0);
    *is_speex = (sound_map == 2 && speex8_enabled == 1 && pcmu_enabled == 0);
}

/* stack_open.xml: flip <enable_speex> in place, to 0 for PCMU or 1 for speex. */
static size_t patch_stack_open(const char *in, size_t in_len, char *out, size_t out_cap, int pcmu) {
    const char *from = pcmu ? "<enable_speex>1</enable_speex>" : "<enable_speex>0</enable_speex>";
    const char *to = pcmu ? "<enable_speex>0</enable_speex>" : "<enable_speex>1</enable_speex>";
    size_t flag_len = strlen(to);
    const char *hit = strstr(in, from);
    size_t oi;
    if (hit == NULL) {
        if (!contains(in, to) || in_len >= out_cap) {
            return 0;
        }
        memcpy(out, in, in_len);
        return in_len;
    }
    oi = (size_t)(hit - in);
    if (in_len + 1 >= out_cap) {
        return 0;
    }
    memcpy(out, in, oi);
    memcpy(out + oi, to, flag_len);
    memcpy(out + oi + flag_len, hit + flag_len, in_len - oi - flag_len);
    return in_len; /* same-length replacement */
}

/* linphone.conf: within [sound] set rtp_ptnum/rtp_map to the codec; within any
 * [audio_codec_*] set enabled by mime (PCMU on and speex/8000 off, or the
 * reverse; speex/16000 is left as it is). Line-based. */
static size_t patch_linphone(const char *in, size_t in_len, char *out, size_t out_cap, int pcmu) {
    size_t oi = 0;
    size_t i = 0;
    char section[64] = "";
    char mime[32] = "";
    char rate[16] = "";
    int saw_rtp_ptnum = 0;
    int saw_rtp_map = 0;
    int saw_pcmu_enabled = 0;
    int saw_speex8_enabled = 0;

    while (i <= in_len) {
        size_t j = i;
        size_t line_len;
        char line[512];
        const char *emit;
        size_t emit_len;
        int has_nl;

        if (i == in_len) {
            break;
        }
        while (j < in_len && in[j] != '\n') {
            j++;
        }
        line_len = j - i;
        has_nl = (j < in_len);
        emit = in + i;
        emit_len = line_len;

        if (line_len < sizeof(line)) {
            memcpy(line, in + i, line_len);
            line[line_len] = '\0';
            if (line[0] == '[') {
                snprintf(section, sizeof(section), "%.63s", line);
                mime[0] = '\0';
                rate[0] = '\0';
            } else if (strcmp(section, "[sound]") == 0) {
                if (strncmp(line, "rtp_ptnum=", 10) == 0) {
                    saw_rtp_ptnum = 1;
                    emit = pcmu ? "rtp_ptnum=0" : "rtp_ptnum=110";
                    emit_len = strlen(emit);
                } else if (strncmp(line, "rtp_map=", 8) == 0) {
                    saw_rtp_map = 1;
                    emit = pcmu ? "rtp_map=PCMU/8000/1" : "rtp_map=speex/8000/1";
                    emit_len = strlen(emit);
                }
            } else if (strncmp(section, "[audio_codec_", 13) == 0) {
                if (strncmp(line, "mime=", 5) == 0) {
                    snprintf(mime, sizeof(mime), "%.31s", line + 5);
                } else if (strncmp(line, "rate=", 5) == 0) {
                    snprintf(rate, sizeof(rate), "%.15s", line + 5);
                } else if (strncmp(line, "enabled=", 8) == 0) {
                    if (strcmp(mime, "PCMU") == 0) {
                        saw_pcmu_enabled = 1;
                        emit = pcmu ? "enabled=1" : "enabled=0";
                        emit_len = strlen(emit);
                    } else if (strcmp(mime, "speex") == 0
                               && strcmp(rate, "8000") == 0) {
                        saw_speex8_enabled = 1;
                        emit = pcmu ? "enabled=0" : "enabled=1";
                        emit_len = strlen(emit);
                    }
                }
            }
        }

        if (oi + emit_len + (has_nl ? 1u : 0u) > out_cap) {
            return 0;
        }
        memcpy(out + oi, emit, emit_len);
        oi += emit_len;
        if (has_nl) {
            out[oi++] = '\n';
        }
        i = has_nl ? j + 1 : j;
    }
    if (!saw_rtp_ptnum || !saw_rtp_map || !saw_pcmu_enabled || !saw_speex8_enabled) {
        return 0;
    }
    return oi;
}

int c300x_audio_codec_read_status(struct c300x_audio_codec_status *status) {
    char sb[C300X_MAX_PATH_LEN];
    char lb[C300X_MAX_PATH_LEN];
    int stack_pcmu;
    int stack_speex;
    int lin_pcmu = 0;
    int lin_speex = 0;

    if (status == NULL) {
        return 0;
    }
    memset(status, 0, sizeof(*status));
    status->supported = access(stack_open_path(), F_OK) == 0
        && access(linphone_path(), F_OK) == 0;
    if (c300x_device_file_backup_path("stack_open.xml", sb, sizeof(sb))
        && c300x_device_file_backup_path("linphone.conf", lb, sizeof(lb))) {
        status->backup_present = access(sb, F_OK) == 0 && access(lb, F_OK) == 0;
    }
    stack_pcmu = stack_open_has("<enable_speex>0</enable_speex>");
    stack_speex = stack_open_has("<enable_speex>1</enable_speex>");
    read_linphone_facts(linphone_path(), &lin_pcmu, &lin_speex);
    if (stack_pcmu && lin_pcmu) {
        snprintf(status->state, sizeof(status->state), "pcmu");
    } else if (stack_speex && lin_speex) {
        snprintf(status->state, sizeof(status->state), "speex");
    } else {
        snprintf(status->state, sizeof(status->state), "partial");
    }
    return 1;
}

static const char *effective_running_state(
    const struct c300x_audio_codec_status *status,
    const char *running_state
) {
    return running_state != NULL && running_state[0] != '\0'
        ? running_state
        : status->state;
}

int c300x_audio_codec_reboot_required(
    const struct c300x_audio_codec_status *status,
    const char *running_state
) {
    return strcmp(effective_running_state(status, running_state), status->state) != 0;
}

void c300x_audio_codec_status_body(
    const struct c300x_audio_codec_status *status,
    const char *running_state,
    char *body,
    size_t body_len
) {
    const char *running = effective_running_state(status, running_state);

    snprintf(
        body,
        body_len,
        "{\"ok\":true,\"supported\":%s,\"state\":\"%s\","
        "\"configured_state\":\"%s\",\"running_state\":\"%s\","
        "\"backup_present\":%s,\"root_writable\":%s,"
        "\"reboot_required\":%s}\n",
        status->supported ? "true" : "false",
        running,
        status->state,
        running,
        status->backup_present ? "true" : "false",
        status->remount_ro_failed ? "true" : "false",
        c300x_audio_codec_reboot_required(status, running) ? "true" : "false"
    );
}

void c300x_audio_codec_action_body(
    const struct c300x_audio_codec_status *status,
    const char *running_state,
    int rebooting,
    char *body,
    size_t body_len
) {
    const char *running = effective_running_state(status, running_state);

    snprintf(
        body,
        body_len,
        "{\"ok\":true,\"supported\":%s,\"state\":\"%s\","
        "\"configured_state\":\"%s\",\"running_state\":\"%s\","
        "\"backup_present\":%s,\"changed\":%s,\"reboot_required\":%s,"
        "\"root_writable\":%s,\"rebooting\":%s}\n",
        status->supported ? "true" : "false",
        running,
        status->state,
        running,
        status->backup_present ? "true" : "false",
        status->changed ? "true" : "false",
        c300x_audio_codec_reboot_required(status, running) ? "true" : "false",
        status->remount_ro_failed ? "true" : "false",
        rebooting ? "true" : "false"
    );
}

/* Read + transform a file into a freshly allocated buffer WITHOUT writing it,
 * so the caller can transform every file before touching any of them. */
static int transform_file(
    const char *path,
    size_t (*transform)(const char *, size_t, char *, size_t, int),
    int pcmu,
    char **out,
    size_t *out_len,
    char *error,
    size_t error_len
) {
    char *data = NULL;
    size_t len = 0;
    char *buffer;
    size_t buffer_len;

    if (!c300x_device_file_read(path, &data, &len, NULL)) {
        set_err(error, error_len, "read_failed");
        return 0;
    }
    buffer = malloc(C300X_DEVICE_FILE_MAX);
    if (buffer == NULL) {
        free(data);
        set_err(error, error_len, "out_of_memory");
        return 0;
    }
    buffer_len = transform(data, len, buffer, C300X_DEVICE_FILE_MAX, pcmu);
    free(data);
    if (buffer_len == 0) {
        free(buffer);
        set_err(error, error_len, "transform_failed");
        return 0;
    }
    *out = buffer;
    *out_len = buffer_len;
    return 1;
}

/* Both directions rewrite the two files the same way; the originals are
 * backed up once, for the removal. */
static int switch_codec(
    struct c300x_audio_codec_status *status,
    int pcmu,
    char *error,
    size_t error_len
) {
    const char *target = pcmu ? "pcmu" : "speex";
    char sb[C300X_MAX_PATH_LEN];
    char lb[C300X_MAX_PATH_LEN];
    char *stack_out = NULL;
    char *lin_out = NULL;
    char *stack_before = NULL;
    size_t stack_len = 0;
    size_t lin_len = 0;
    size_t stack_before_len = 0;
    int ro_failed;

    if (!c300x_audio_codec_read_status(status)) {
        set_err(error, error_len, "status_failed");
        return 0;
    }
    if (!status->supported) {
        set_err(error, error_len, "missing_config");
        return 0;
    }
    if (strcmp(status->state, target) == 0) {
        return 1; /* idempotent */
    }
    if (!c300x_device_file_backup_path("stack_open.xml", sb, sizeof(sb))
        || !c300x_device_file_backup_path("linphone.conf", lb, sizeof(lb))) {
        set_err(error, error_len, "backup_path_failed");
        return 0;
    }
    if (!c300x_device_file_remount("rw")) {
        set_err(error, error_len, "remount_rw_failed");
        return 0;
    }
    if (!c300x_device_file_mkdir_p(c300x_device_file_backup_dir())) {
        (void)c300x_device_file_remount("ro");
        set_err(error, error_len, "backup_dir_failed");
        return 0;
    }
    if (!c300x_device_file_backup_once(stack_open_path(), sb) || !c300x_device_file_backup_once(linphone_path(), lb)) {
        (void)c300x_device_file_remount("ro");
        set_err(error, error_len, "backup_failed");
        return 0;
    }
    /* Transform BOTH files in memory first; only if both succeed do we write
     * either, so a transform failure can never leave one file half-patched
     * (an inconsistent speex/PCMU mix = garbage audio until restore). */
    if (!transform_file(stack_open_path(), patch_stack_open, pcmu, &stack_out, &stack_len, error, error_len)
        || !transform_file(linphone_path(), patch_linphone, pcmu, &lin_out, &lin_len, error, error_len)
        || !c300x_device_file_read(stack_open_path(), &stack_before, &stack_before_len, NULL)) {
        if (stack_out != NULL && lin_out != NULL) {
            set_err(error, error_len, "read_failed");
        }
        free(stack_out);
        free(lin_out);
        free(stack_before);
        (void)c300x_device_file_remount("ro");
        return 0;
    }
    /* Each write is atomic, so a file is either fully old or new. When the
     * second write fails, stack_open.xml gets its content from before this
     * switch back: the backups hold the original codec, which is not
     * necessarily the one the device had before. */
    if (!c300x_device_file_write(stack_open_path(), stack_out, stack_len)
        || !c300x_device_file_write(linphone_path(), lin_out, lin_len)) {
        (void)c300x_device_file_write(stack_open_path(), stack_before, stack_before_len);
        free(stack_out);
        free(lin_out);
        free(stack_before);
        (void)c300x_device_file_remount("ro");
        set_err(error, error_len, "write_failed");
        return 0;
    }
    free(stack_out);
    free(lin_out);
    free(stack_before);
    /* The device files are already written. A busy root cannot undo that, and
     * the boot after this switch mounts read-only again, so report the failed
     * remount instead of failing an operation that succeeded. */
    ro_failed = !c300x_device_file_remount("ro");
    if (!c300x_audio_codec_read_status(status)) {
        set_err(error, error_len, "status_failed");
        return 0;
    }
    if (strcmp(status->state, target) != 0) {
        set_err(error, error_len, "target_state_mismatch");
        return 0;
    }
    status->remount_ro_failed = ro_failed;
    status->changed = 1;
    return 1;
}

int c300x_audio_codec_apply(struct c300x_audio_codec_status *status, char *error, size_t error_len)
{
    /* C100X firmware PCMU cannot work: the device PCM runs at 16 kHz and
     * rtppcmupay accepts only 8 kHz. The agent's PCMU transcode is independent. */
    if (c300x_device_model() == C300X_DEVICE_MODEL_C100X) {
        set_err(error, error_len, C300X_AUDIO_CODEC_TEST_BUILD_BLOCKED);
        return 0;
    }
    return switch_codec(status, 1, error, error_len);
}

static int stock_speex_backup(void)
{
    char sb[C300X_MAX_PATH_LEN], lb[C300X_MAX_PATH_LEN];
    char *original = NULL, *normalized = NULL;
    size_t original_len = 0, normalized_len = 0;
    int pcmu = 0, speex = 0;
    int valid = 0;

    if (!c300x_device_file_backup_path("stack_open.xml", sb, sizeof(sb))
        || !c300x_device_file_backup_path("linphone.conf", lb, sizeof(lb))
        || !file_has(sb, "<enable_speex>1</enable_speex>")
        || file_has(sb, "<enable_speex>0</enable_speex>")) {
        return 0;
    }
    read_linphone_facts(lb, &pcmu, &speex);
    /* Validate every field the switch owns, including payload 110. A missing,
     * partial or PCMU backup must not authorize a new C100X codec mutation. */
    if (speex && transform_file(lb, patch_linphone, 0, &normalized, &normalized_len, NULL, 0)
        && c300x_device_file_read(lb, &original, &original_len, NULL)) {
        valid = original_len == normalized_len && memcmp(original, normalized, original_len) == 0;
    }
    free(original);
    free(normalized);
    return valid;
}

/* Speex, also where the device came with PCMU (firmware 3.0.x). */
int c300x_audio_codec_restore(struct c300x_audio_codec_status *status, char *error, size_t error_len)
{
    if (c300x_device_model() == C300X_DEVICE_MODEL_C100X && !stock_speex_backup()) {
        set_err(error, error_len, C300X_AUDIO_CODEC_RECOVERY_BLOCKED);
        return 0;
    }
    return switch_codec(status, 0, error, error_len);
}

/* The codec the device came with, from the backups of the first switch. */
static int original_codec_is_pcmu(const char *sb, const char *lb, int *pcmu)
{
    int lin_pcmu = 0;
    int lin_speex = 0;

    if (file_has(sb, "<enable_speex>0</enable_speex>") || file_has(sb, "<enable_speex>1</enable_speex>")) {
        *pcmu = file_has(sb, "<enable_speex>0</enable_speex>");
        return 1;
    }
    read_linphone_facts(lb, &lin_pcmu, &lin_speex);
    *pcmu = lin_pcmu;
    return lin_pcmu || lin_speex;
}

int c300x_audio_codec_remove_patches(char *error, size_t error_len)
{
    char sb[C300X_MAX_PATH_LEN];
    char lb[C300X_MAX_PATH_LEN];
    struct c300x_audio_codec_status status;
    int pcmu = 0;

    if (!c300x_device_file_backup_path("stack_open.xml", sb, sizeof(sb))
        || !c300x_device_file_backup_path("linphone.conf", lb, sizeof(lb))) {
        set_err(error, error_len, "backup_path_failed");
        return 0;
    }
    if (access(sb, F_OK) != 0 && access(lb, F_OK) != 0) {
        return 1; /* No managed codec changes on this device. */
    }
    if (c300x_device_model() == C300X_DEVICE_MODEL_C100X) {
        return c300x_audio_codec_restore(&status, error, error_len);
    }
    /* Only the codec lines go back: a firmware update may have replaced the
     * rest of both files since the backups were taken. */
    if (!original_codec_is_pcmu(sb, lb, &pcmu)) {
        set_err(error, error_len, "no_backup");
        return 0;
    }
    return switch_codec(&status, pcmu, error, error_len);
}
