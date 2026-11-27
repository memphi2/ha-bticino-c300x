#include "audio_chip.h"

#include "device_detect.h"
#include "device_file.h"
#include "sha256.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sound/asound.h>
#include <unistd.h>

#define SOUT_CONTROL "ZL0 Sout Gain Volume"
#define HOOK_BACKUP_NAME "Audio_State.sh"
#define HOOK_MAX 2048
/* Every version of our hook carries this line; the level is its V= line. An
 * agent recognises an older or newer template by it and rewrites it. */
#define HOOK_MARKER "# c300x-agent audio hook "
/* The vendor's empty Audio_State.sh and IP_PE.cr, the same bytes on 1.7.19,
 * 2.0.2 and 3.0.6. */
#ifndef STOCK_HOOK_SHA256
#define STOCK_HOOK_SHA256 "358cd68c78aa70569e9ec4546afa8c4ff33227f4bf21d8a586ae93a3a0a15aa8"
#endif
/* What goes back when the backup of the stub is lost or broken: no vendor
 * bytes in the agent, only the stub's behaviour (exit 1 for every state, no
 * mixer change). It counts as stock from then on. The stock file is 0775. */
#define NEUTRAL_STUB "#!/bin/sh\nexit 1\n"
#define STUB_MODE 0775
#ifndef IP_PROFILE_SHA256
#define IP_PROFILE_SHA256 "03d9dfe656d6d2fc7b367cae47e0b0f01e73ed801fda219ded15e5341488b6bc"
#endif

/* The HAL runs it as root at every audio state change and expects exit 1,
 * like the stub. The mark comes whole (renamed into place) and before the
 * raise: the agent reads the live value while it is there, so a mark without
 * the raise yet counts 0 dB, never the other way round. The states the vendor stub lists, apart from OFF, IP_EU and
 * IP_IU, load a profile with its own gain; anything else (FAKE, an empty or
 * unknown state) gets the profile's 11 back, so nothing leaves it raised. */
static const char hook_template[] =
    "#!/bin/sh\n"
    HOOK_MARKER "v1\n"
    "V=%d\n"
    "A=${C300X_AMIXER:-/usr/bin/amixer}\n"
    "M=${C300X_SOUT_MARK:-/run/c300x-sout-raised}\n"
    "put() { \"$A\" -q -c 0 cset \"name='" SOUT_CONTROL "'\" \"$1\" >/dev/null 2>&1; }\n"
    "case \"$1\" in\n"
    "EN_AUDIO_IP_EU) echo \"$V\" > \"$M.new\" && mv -f \"$M.new\" \"$M\" && put \"$V\" || rm -f \"$M\" \"$M.new\";;\n"
    "EN_AUDIO_BEEP|EN_AUDIO_PASSTHR|EN_AUDIO_PASSTHR_INT|EN_AUDIO_IP|EN_AUDIO_RINGING|EN_AUDIO_RINGING_LOC"
    "|EN_AUDIO_PLAY_LOC|EN_AUDIO_PLAY_LOC_SCS|EN_AUDIO_REC_SCS|EN_AUDIO_REC_MIC) rm -f \"$M\";;\n"
    "*) [ ! -e \"$M\" ] || put 11; rm -f \"$M\";;\n"
    "esac\n"
    "exit 1\n";

static const char *env_path(const char *name, const char *fallback)
{
    const char *value = getenv(name);
    return value != NULL && value[0] != '\0' ? value : fallback;
}

static const char *hook_path(void)
{
    return env_path("C300X_AUDIO_STATE_HOOK", "/home/root/demo/Audio_State.sh");
}

static const char *mark_path(void)
{
    return env_path("C300X_SOUT_MARK", "/run/c300x-sout-raised");
}

static void set_err(char *error, size_t error_len, const char *message)
{
    if (error != NULL && error_len > 0) {
        snprintf(error, error_len, "%s", message);
    }
}

size_t c300x_audio_chip_render_hook(int steps, char *out, size_t out_len)
{
    int written = snprintf(out, out_len, hook_template, C300X_AUDIO_CHIP_STOCK_SOUT + steps);
    return written > 0 && (size_t)written < out_len ? (size_t)written : 0;
}

static int sha_matches(const char *data, size_t len, const char *expected)
{
    char hex[65];
    return c300x_sha256_bytes_hex((const unsigned char *)data, len, hex, sizeof(hex))
        && strcmp(hex, expected) == 0;
}

static int is_stub(const char *data, size_t len)
{
    return sha_matches(data, len, STOCK_HOOK_SHA256)
        || (len == sizeof(NEUTRAL_STUB) - 1 && memcmp(data, NEUTRAL_STUB, len) == 0);
}

/* The level a hook of ours carries, 0 when its V= line is not one. */
static int hook_steps(const char *data)
{
    const char *at = strstr(data, "\nV=");
    char *end = NULL;
    long value;

    if (at == NULL) {
        return 0;
    }
    value = strtol(at + 3, &end, 10);
    if (end == at + 3 || *end != '\n' || value <= C300X_AUDIO_CHIP_STOCK_SOUT || value > C300X_AUDIO_CHIP_MAX_SOUT) {
        return 0;
    }
    return (int)value - C300X_AUDIO_CHIP_STOCK_SOUT;
}

/* data is NUL-terminated (c300x_device_file_read). *current: the bytes are
 * exactly what this agent renders for that level. */
static enum c300x_audio_hook_state classify(const char *data, size_t len, int *steps, int *current)
{
    char ours[HOOK_MAX];
    size_t ours_len;

    *steps = 0;
    *current = 0;
    if (is_stub(data, len)) {
        return C300X_AUDIO_HOOK_STOCK;
    }
    if (strlen(data) != len || strncmp(data, "#!", 2) != 0 || strstr(data, "\n" HOOK_MARKER) == NULL) {
        return C300X_AUDIO_HOOK_FOREIGN;
    }
    *steps = hook_steps(data);
    ours_len = *steps > 0 ? c300x_audio_chip_render_hook(*steps, ours, sizeof(ours)) : 0;
    *current = ours_len == len && memcmp(ours, data, len) == 0;
    return C300X_AUDIO_HOOK_OURS;
}

static enum c300x_audio_hook_state hook_state(int *steps, int *current)
{
    char *data = NULL;
    size_t len = 0;
    enum c300x_audio_hook_state state;

    *steps = 0;
    *current = 0;
    if (!c300x_device_file_read(hook_path(), &data, &len, NULL)) {
        return C300X_AUDIO_HOOK_MISSING;
    }
    state = classify(data, len, steps, current);
    free(data);
    return state;
}

enum c300x_audio_hook_state c300x_audio_chip_hook_state(int *steps)
{
    int found = 0;
    int current = 0;
    enum c300x_audio_hook_state state = hook_state(&found, &current);

    if (steps != NULL) {
        *steps = found;
    }
    return state;
}

/* A test names a plain file holding the value instead of the ALSA control. */
static int sout_stand_in(int *value, int write_value)
{
    const char *path = getenv("C300X_SOUT_GAIN_FILE");
    FILE *fp;
    int ok;

    if (path == NULL || path[0] == '\0') {
        return -1;
    }
    fp = fopen(path, write_value >= 0 ? "we" : "re");
    if (fp == NULL) {
        return 0;
    }
    ok = write_value >= 0 ? fprintf(fp, "%d\n", write_value) > 0 : fscanf(fp, "%d", value) == 1;
    return fclose(fp) == 0 && ok;
}

/* One ALSA control ioctl on card 0, no library and no child process. */
static int sout_control(int *value, int write_value)
{
    struct snd_ctl_elem_value control;
    int stand_in = sout_stand_in(value, write_value);
    int fd;
    int ok;

    if (stand_in >= 0) {
        return stand_in;
    }
    fd = open(env_path("C300X_ALSA_CONTROL", "/dev/snd/controlC0"), O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        return 0;
    }
    memset(&control, 0, sizeof(control));
    control.id.iface = SNDRV_CTL_ELEM_IFACE_MIXER;
    snprintf((char *)control.id.name, sizeof(control.id.name), "%s", SOUT_CONTROL);
    if (write_value >= 0) {
        control.value.integer.value[0] = write_value;
        ok = ioctl(fd, SNDRV_CTL_IOCTL_ELEM_WRITE, &control) >= 0;
    } else {
        ok = ioctl(fd, SNDRV_CTL_IOCTL_ELEM_READ, &control) == 0;
        *value = (int)control.value.integer.value[0];
    }
    close(fd);
    return ok;
}

static int read_sout(int *value)
{
    int read_value = -1;
    if (!sout_control(&read_value, -1) || read_value < 0 || read_value > C300X_AUDIO_CHIP_MAX_SOUT) {
        return 0;
    }
    *value = read_value;
    return 1;
}

int c300x_audio_chip_supported(void)
{
    char hex[65];
    int value;

    return c300x_device_model() == C300X_DEVICE_MODEL_C300X
        && c300x_sha256_file_hex(env_path("C300X_ZL_IP_PROFILE", "/home/bticino/microsemi/IP_PE.cr"), hex, sizeof(hex))
        && strcmp(hex, IP_PROFILE_SHA256) == 0
        && access(env_path("C300X_AMIXER", "/usr/bin/amixer"), X_OK) == 0
        && read_sout(&value);
}

static int read_mark(int *value)
{
    FILE *fp = fopen(mark_path(), "re");
    int ok;

    if (fp == NULL) {
        return 0;
    }
    ok = fscanf(fp, "%d", value) == 1 && *value > C300X_AUDIO_CHIP_STOCK_SOUT
        && *value <= C300X_AUDIO_CHIP_MAX_SOUT;
    fclose(fp);
    return ok;
}

int c300x_audio_chip_current_db(int *db)
{
    int marked = 0;
    int parsed;
    int value;

    *db = 0;
    if (access(mark_path(), F_OK) != 0) {
        return 1;
    }
    /* The live value wins: a level changed during the call is not in the
     * chip before the next state change. A mark caught half written still
     * says the hook raised the gain. */
    parsed = read_mark(&marked);
    if (!read_sout(&value)) {
        if (!parsed) {
            return 0;
        }
        value = marked;
    }
    *db = (value - C300X_AUDIO_CHIP_STOCK_SOUT) * C300X_AUDIO_CHIP_DB_PER_STEP;
    return 1;
}

static int hook_backup_path(char *out, size_t out_len)
{
    return c300x_device_file_backup_path(HOOK_BACKUP_NAME, out, out_len);
}

static int write_hook(const char *data, size_t len, const char *backup, char *error, size_t error_len)
{
    int ok;

    if (!c300x_device_file_remount("rw")) {
        set_err(error, error_len, "remount_rw_failed");
        return 0;
    }
    /* The source is the verified stub: an older, other backup gives way.
     * The hook keeps the mode of the file it replaces. */
    ok = backup == NULL
        || (c300x_device_file_mkdir_p(c300x_device_file_backup_dir())
            && c300x_device_file_copy(hook_path(), backup));
    if (!ok) {
        set_err(error, error_len, "backup_failed");
    } else if (!(ok = c300x_device_file_write_mode(hook_path(), data, len, STUB_MODE))) {
        set_err(error, error_len, "write_failed");
    }
    /* Written is written: a busy root closes at the next boot. */
    (void)c300x_device_file_remount("ro");
    return ok;
}

/* The backup must be the stub: never put anything else back. */
static int read_stock_backup(char **data, size_t *len)
{
    char backup[512];

    if (!hook_backup_path(backup, sizeof(backup)) || !c300x_device_file_read(backup, data, len, NULL)) {
        return 0;
    }
    if (!is_stub(*data, *len)) {
        free(*data);
        *data = NULL;
        return 0;
    }
    return 1;
}

/* A call that ends after the stub is back runs no hook of ours any more:
 * put the profile's value back now. */
static void lower_raised_gain(void)
{
    int unused = 0;

    if (access(mark_path(), F_OK) == 0) {
        (void)sout_control(&unused, C300X_AUDIO_CHIP_STOCK_SOUT);
        (void)unlink(mark_path());
    }
}

static int restore_stub(char *error, size_t error_len)
{
    char *stock = NULL;
    size_t stock_len = 0;
    int ok;

    if (c300x_audio_chip_hook_state(NULL) != C300X_AUDIO_HOOK_OURS) {
        return 1;
    }
    /* A lost backup never keeps our hook in place: the neutral stub. */
    if (read_stock_backup(&stock, &stock_len)) {
        ok = write_hook(stock, stock_len, NULL, error, error_len);
        free(stock);
    } else {
        ok = write_hook(NEUTRAL_STUB, sizeof(NEUTRAL_STUB) - 1, NULL, error, error_len);
    }
    if (ok) {
        lower_raised_gain();
    }
    return ok;
}

int c300x_audio_chip_apply(int steps, char *error, size_t error_len)
{
    char hook[HOOK_MAX];
    char backup[512];
    size_t hook_len;
    int current = 0;
    int exact = 0;
    enum c300x_audio_hook_state state;

    if (steps < 0 || steps > C300X_AUDIO_CHIP_MAX_STEPS) {
        set_err(error, error_len, "invalid_level");
        return 0;
    }
    if (steps == 0) {
        return restore_stub(error, error_len);
    }
    state = hook_state(&current, &exact);
    if (state == C300X_AUDIO_HOOK_OURS && current == steps && exact) {
        return 1;
    }
    if (state != C300X_AUDIO_HOOK_STOCK && state != C300X_AUDIO_HOOK_OURS) {
        set_err(error, error_len, state == C300X_AUDIO_HOOK_MISSING ? "hook_missing" : "hook_foreign");
        return 0;
    }
    hook_len = c300x_audio_chip_render_hook(steps, hook, sizeof(hook));
    if (hook_len == 0 || !hook_backup_path(backup, sizeof(backup))) {
        set_err(error, error_len, "render_failed");
        return 0;
    }
    return write_hook(hook, hook_len, state == C300X_AUDIO_HOOK_STOCK ? backup : NULL, error, error_len);
}

int c300x_audio_chip_remove_patches(char *error, size_t error_len)
{
    return restore_stub(error, error_len);
}
