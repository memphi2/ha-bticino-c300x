#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#include "audio_codec.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <sys/stat.h>
#include <unistd.h>

#define C300X_AUDIO_MAX_FILE 262144

/* The target's old glibc (2.26) has no plain `stat` symbol; mirror the
 * device_routing.c portable stat64 syscall shim used across this agent. */
#ifdef __arm__
#define C300X_AUDIO_STAT_STRUCT struct stat64
#else
#define C300X_AUDIO_STAT_STRUCT struct stat
#endif

static int audio_stat_path(const char *path, C300X_AUDIO_STAT_STRUCT *status) {
#ifdef __arm__
    return (int)syscall(SYS_stat64, path, status);
#else
    return stat(path, status);
#endif
}

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

static const char *backup_dir(void) {
    const char *p = getenv("C300X_AUDIO_BACKUP_DIR");
    return (p != NULL && p[0] != '\0')
        ? p
        : "/home/bticino/cfg/extra/c300x-device-file-backups/original";
}

static int no_remount(void) {
    const char *p = getenv("C300X_AUDIO_NO_REMOUNT");
    return p != NULL && strcmp(p, "1") == 0;
}

static void set_err(char *error, size_t error_len, const char *message) {
    if (error != NULL && error_len > 0) {
        snprintf(error, error_len, "%s", message);
    }
}

static int join_backup(const char *name, char *out, size_t out_len) {
    int written = snprintf(out, out_len, "%s/%s", backup_dir(), name);
    return written >= 0 && written < (int)out_len;
}

static int remount(const char *mode) {
    char command[64];
    if (no_remount()) {
        return 1;
    }
    if (snprintf(command, sizeof(command), "mount -o remount,%s / >/dev/null 2>&1", mode)
        >= (int)sizeof(command)) {
        return 0;
    }
    return system(command) == 0;
}

static int read_file(const char *path, char **data, size_t *len, mode_t *mode) {
    C300X_AUDIO_STAT_STRUCT st;
    FILE *fp;
    char *buffer;
    size_t got;

    if (audio_stat_path(path, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size < 0
        || (size_t)st.st_size > C300X_AUDIO_MAX_FILE) {
        return 0;
    }
    fp = fopen(path, "rb");
    if (fp == NULL) {
        return 0;
    }
    buffer = malloc((size_t)st.st_size + 1);
    if (buffer == NULL) {
        fclose(fp);
        return 0;
    }
    got = fread(buffer, 1, (size_t)st.st_size, fp);
    fclose(fp);
    if (got != (size_t)st.st_size) {
        free(buffer);
        return 0;
    }
    buffer[got] = '\0';
    *data = buffer;
    *len = got;
    if (mode != NULL) {
        *mode = (mode_t)(st.st_mode & 07777);
    }
    return 1;
}

/* Write data to path atomically: write a sibling temp file, fsync it, then
 * rename it over the target. A mid-write failure (short fwrite, fsync error,
 * full partition, power loss) therefore leaves the ORIGINAL file intact instead
 * of a truncated/corrupt live config. When the target already exists we copy its
 * owner+mode onto the temp first (the rename gives a new inode), preserving what
 * the old in-place write kept for free; new targets (backup creation) get the
 * default mode and the caller sets it explicitly afterwards. */
static int overwrite_file(const char *path, const char *data, size_t len) {
    C300X_AUDIO_STAT_STRUCT st;
    int have_meta = audio_stat_path(path, &st) == 0 && S_ISREG(st.st_mode);
    char tmp[C300X_MAX_PATH_LEN];
    FILE *fp;
    int fd;
    int ok = 1;

    if (snprintf(tmp, sizeof(tmp), "%s.tmp", path) >= (int)sizeof(tmp)) {
        return 0;
    }
    fp = fopen(tmp, "wb");
    if (fp == NULL) {
        return 0;
    }
    fd = fileno(fp);
    if (fwrite(data, 1, len, fp) != len) {
        ok = 0;
    }
    if (fflush(fp) != 0 || fsync(fd) != 0) {
        ok = 0;
    }
    if (ok && have_meta) {
        /* rename creates a new inode, so restore the original owner/mode */
        if (fchmod(fd, st.st_mode & 07777) != 0
            || fchown(fd, st.st_uid, st.st_gid) != 0) {
            ok = 0;
        }
    }
    if (fclose(fp) != 0) {
        ok = 0;
    }
    if (ok && rename(tmp, path) == 0) {
        return 1;
    }
    (void)unlink(tmp);
    return 0;
}

/* Copy source to dest preserving source mode; used for one-time backup and for
 * restore. Never overwrites an existing backup. */
static int copy_new(const char *source, const char *dest) {
    char *data = NULL;
    size_t len = 0;
    mode_t mode = 0600;
    int ok;
    if (!read_file(source, &data, &len, &mode)) {
        return 0;
    }
    ok = overwrite_file(dest, data, len);
    free(data);
    if (ok) {
        (void)chmod(dest, mode);
    }
    return ok;
}

static int mkdir_p(const char *path) {
    char tmp[C300X_MAX_PATH_LEN];
    size_t len = strlen(path);
    char *p;
    if (len == 0 || len >= sizeof(tmp)) {
        return 0;
    }
    memcpy(tmp, path, len + 1);
    for (p = tmp + 1; *p != '\0'; p++) {
        if (*p == '/') {
            *p = '\0';
            if (mkdir(tmp, 0755) != 0 && errno != EEXIST) {
                return 0;
            }
            *p = '/';
        }
    }
    return mkdir(tmp, 0755) == 0 || errno == EEXIST;
}

static int backup_once(const char *source, const char *dest) {
    if (access(dest, F_OK) == 0) {
        return 1;
    }
    return copy_new(source, dest);
}

static int contains(const char *data, const char *needle) {
    return data != NULL && strstr(data, needle) != NULL;
}

static int stack_open_has(const char *needle) {
    char *data = NULL;
    size_t len = 0;
    int hit;
    if (!read_file(stack_open_path(), &data, &len, NULL)) {
        return 0;
    }
    hit = contains(data, needle);
    free(data);
    return hit;
}

static void read_linphone_facts(int *is_pcmu, int *is_speex);

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
    read_linphone_facts(&lin_pcmu, &lin_speex);
    return lin_pcmu;
}

/* Parse linphone.conf once into two consistency verdicts. A fully-PCMU config
 * needs [sound] rtp_map=PCMU AND the PCMU codec enabled AND speex/8000
 * disabled; fully-speex (stock) is the mirror. Anything else is neither, so the
 * caller reports "partial" — this catches half-applied states the old
 * rtp_map-only check missed. Line-based, mirrors patch_linphone's section walk. */
static void read_linphone_facts(int *is_pcmu, int *is_speex) {
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
    if (!read_file(linphone_path(), &data, &len, NULL)) {
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

/* stack_open.xml: flip <enable_speex>1</enable_speex> to ...0... in place. */
static size_t patch_stack_open(const char *in, size_t in_len, char *out, size_t out_cap) {
    static const char from[] = "<enable_speex>1</enable_speex>";
    static const char to[] = "<enable_speex>0</enable_speex>";
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
    memcpy(out + oi, to, sizeof(to) - 1);
    memcpy(out + oi + (sizeof(to) - 1), hit + (sizeof(from) - 1),
           in_len - oi - (sizeof(from) - 1));
    return in_len; /* same-length replacement */
}

/* linphone.conf: within [sound] set rtp_ptnum/rtp_map to PCMU; within any
 * [audio_codec_*] set enabled by mime (PCMU on, speex off). Line-based, mirrors
 * the reference audio_codec_patch.sh awk transform. */
static size_t patch_linphone(const char *in, size_t in_len, char *out, size_t out_cap) {
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
                    emit = "rtp_ptnum=0";
                    emit_len = strlen(emit);
                } else if (strncmp(line, "rtp_map=", 8) == 0) {
                    saw_rtp_map = 1;
                    emit = "rtp_map=PCMU/8000/1";
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
                        emit = "enabled=1";
                        emit_len = strlen(emit);
                    } else if (strcmp(mime, "speex") == 0
                               && strcmp(rate, "8000") == 0) {
                        saw_speex8_enabled = 1;
                        emit = "enabled=0";
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
    if (join_backup("stack_open.xml", sb, sizeof(sb))
        && join_backup("linphone.conf", lb, sizeof(lb))) {
        status->backup_present = access(sb, F_OK) == 0 && access(lb, F_OK) == 0;
    }
    stack_pcmu = stack_open_has("<enable_speex>0</enable_speex>");
    stack_speex = stack_open_has("<enable_speex>1</enable_speex>");
    read_linphone_facts(&lin_pcmu, &lin_speex);
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
        "\"backup_present\":%s,\"reboot_required\":%s}\n",
        status->supported ? "true" : "false",
        running,
        status->state,
        running,
        status->backup_present ? "true" : "false",
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
        "\"rebooting\":%s}\n",
        status->supported ? "true" : "false",
        running,
        status->state,
        running,
        status->backup_present ? "true" : "false",
        status->changed ? "true" : "false",
        c300x_audio_codec_reboot_required(status, running) ? "true" : "false",
        rebooting ? "true" : "false"
    );
}

/* Read + transform a file into a freshly allocated buffer WITHOUT writing it,
 * so the caller can transform every file before touching any of them. */
static int transform_file(
    const char *path,
    size_t (*transform)(const char *, size_t, char *, size_t),
    char **out,
    size_t *out_len,
    char *error,
    size_t error_len
) {
    char *data = NULL;
    size_t len = 0;
    char *buffer;
    size_t buffer_len;

    if (!read_file(path, &data, &len, NULL)) {
        set_err(error, error_len, "read_failed");
        return 0;
    }
    buffer = malloc(C300X_AUDIO_MAX_FILE);
    if (buffer == NULL) {
        free(data);
        set_err(error, error_len, "out_of_memory");
        return 0;
    }
    buffer_len = transform(data, len, buffer, C300X_AUDIO_MAX_FILE);
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

int c300x_audio_codec_apply(
    struct c300x_audio_codec_status *status,
    char *error,
    size_t error_len
) {
    char sb[C300X_MAX_PATH_LEN];
    char lb[C300X_MAX_PATH_LEN];
    char *stack_out = NULL;
    char *lin_out = NULL;
    size_t stack_len = 0;
    size_t lin_len = 0;

    if (!c300x_audio_codec_read_status(status)) {
        set_err(error, error_len, "status_failed");
        return 0;
    }
    if (!status->supported) {
        set_err(error, error_len, "missing_config");
        return 0;
    }
    if (strcmp(status->state, "pcmu") == 0) {
        return 1; /* idempotent */
    }
    if (!join_backup("stack_open.xml", sb, sizeof(sb))
        || !join_backup("linphone.conf", lb, sizeof(lb))) {
        set_err(error, error_len, "backup_path_failed");
        return 0;
    }
    if (!remount("rw")) {
        set_err(error, error_len, "remount_rw_failed");
        return 0;
    }
    if (!mkdir_p(backup_dir())) {
        (void)remount("ro");
        set_err(error, error_len, "backup_dir_failed");
        return 0;
    }
    if (!backup_once(stack_open_path(), sb) || !backup_once(linphone_path(), lb)) {
        (void)remount("ro");
        set_err(error, error_len, "backup_failed");
        return 0;
    }
    /* Transform BOTH files in memory first; only if both succeed do we write
     * either, so a transform failure can never leave one file half-patched
     * (an inconsistent speex/PCMU mix = garbage audio until restore). */
    if (!transform_file(stack_open_path(), patch_stack_open, &stack_out, &stack_len, error, error_len)
        || !transform_file(linphone_path(), patch_linphone, &lin_out, &lin_len, error, error_len)) {
        free(stack_out);
        free(lin_out);
        (void)remount("ro");
        return 0;
    }
    if (!overwrite_file(stack_open_path(), stack_out, stack_len)
        || !overwrite_file(linphone_path(), lin_out, lin_len)) {
        /* The first write may have already flipped stack_open.xml before the
         * second failed. Roll both files back from the backups so we never
         * leave a mixed speex/PCMU state (garbage audio until a manual restore).
         * overwrite_file is atomic, so each file is either fully old or new. */
        (void)copy_new(sb, stack_open_path());
        (void)copy_new(lb, linphone_path());
        free(stack_out);
        free(lin_out);
        (void)remount("ro");
        set_err(error, error_len, "write_failed");
        return 0;
    }
    free(stack_out);
    free(lin_out);
    if (!remount("ro")) {
        set_err(error, error_len, "remount_ro_failed");
        return 0;
    }
    if (!c300x_audio_codec_read_status(status)) {
        set_err(error, error_len, "status_failed");
        return 0;
    }
    if (strcmp(status->state, "pcmu") != 0) {
        set_err(error, error_len, "target_state_mismatch");
        return 0;
    }
    status->changed = 1;
    return 1;
}

int c300x_audio_codec_restore(
    struct c300x_audio_codec_status *status,
    char *error,
    size_t error_len
) {
    char sb[C300X_MAX_PATH_LEN];
    char lb[C300X_MAX_PATH_LEN];

    if (!c300x_audio_codec_read_status(status)) {
        set_err(error, error_len, "status_failed");
        return 0;
    }
    if (!status->supported) {
        set_err(error, error_len, "missing_config");
        return 0;
    }
    if (strcmp(status->state, "speex") == 0) {
        return 1; /* idempotent */
    }
    if (!join_backup("stack_open.xml", sb, sizeof(sb))
        || !join_backup("linphone.conf", lb, sizeof(lb))) {
        set_err(error, error_len, "backup_path_failed");
        return 0;
    }
    if (access(sb, F_OK) != 0 || access(lb, F_OK) != 0) {
        set_err(error, error_len, "no_backup");
        return 0;
    }
    if (!remount("rw")) {
        set_err(error, error_len, "remount_rw_failed");
        return 0;
    }
    if (!copy_new(sb, stack_open_path()) || !copy_new(lb, linphone_path())) {
        /* A partial restore (one file copied, the other not) also leaves a mixed
         * state; re-copy both backups to roll forward to the fully-restored
         * target (copy_new is idempotent). */
        (void)copy_new(sb, stack_open_path());
        (void)copy_new(lb, linphone_path());
        (void)remount("ro");
        set_err(error, error_len, "restore_failed");
        return 0;
    }
    if (!remount("ro")) {
        set_err(error, error_len, "remount_ro_failed");
        return 0;
    }
    if (!c300x_audio_codec_read_status(status)) {
        set_err(error, error_len, "status_failed");
        return 0;
    }
    if (strcmp(status->state, "speex") != 0) {
        set_err(error, error_len, "target_state_mismatch");
        return 0;
    }
    status->changed = 1;
    return 1;
}
