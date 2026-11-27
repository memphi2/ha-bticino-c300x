#include "audio_level.h"

#include "audio_chip.h"
#include "audio_gain.h"
#include "media_audio.h"
#include "pthread_compat.h"
#include "time_util.h"

#include <stdio.h>
#include <string.h>

/* How often the packet path looks at the chip while sound flows: the HAL
 * changes the state, and with it the chip's gain, at its own time, mostly
 * around the start of the sound. For CHIP_START_MS after a start every packet
 * looks (bursts at most every CHIP_START_CHECK_MS), later every CHIP_CHECK_MS.
 * A start is a session boundary or the first packet after AUDIO_GAP_MS of
 * none. Before the hook has raised the gain the chip has no mark and a look
 * is one access(); with the mark it is one tmpfs read and one ALSA ioctl. */
#define CHIP_CHECK_MS 500
#define CHIP_START_MS 2000
#define CHIP_START_CHECK_MS 10
#define AUDIO_GAP_MS 100

static pthread_mutex_t level_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t set_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t level_once = PTHREAD_ONCE_INIT;

static struct {
    int door_db;
    int fine_db;
    int hook_ours;
    int observed;
    int chip_db;
    /* Counts every set() and session boundary: a chip read begun before
     * one is stale. */
    unsigned generation;
    long long chip_checked_ms;
    /* 0: no sound since the last session boundary. */
    long long audio_start_ms;
    long long last_audio_ms;
    const char *lever;
    struct c300x_audio_gain gain;
} level = {.lever = "unsupported"};

static void rebuild_locked(void)
{
    int db = c300x_audio_gain_clamp_db(level.fine_db + level.door_db - level.chip_db);
    if (db != level.gain.db) {
        c300x_audio_gain_init(&level.gain, db);
    }
}

static const char *lever_for(int door_db, int supported, int hook_ours)
{
    if (!supported) {
        return "unsupported";
    }
    if (door_db == 0) {
        return "off";
    }
    return hook_ours ? "ready" : "not_installed";
}

/* After a restart the hook still holds the door level that was set. */
static void level_init(void)
{
    int steps = 0;
    int ours = c300x_audio_chip_hook_state(&steps) == C300X_AUDIO_HOOK_OURS;
    int supported = c300x_audio_chip_supported();

    pthread_mutex_lock(&level_lock);
    level.door_db = ours ? steps * C300X_AUDIO_CHIP_DB_PER_STEP : 0;
    level.hook_ours = ours;
    level.lever = lever_for(level.door_db, supported, ours);
    c300x_audio_gain_init(&level.gain, level.door_db + level.fine_db);
    pthread_mutex_unlock(&level_lock);
}

static void ensure_init(void)
{
    pthread_once(&level_once, level_init);
}

int c300x_audio_level_valid(int door_level_db, int fine_gain_db)
{
    return door_level_db >= 0 && door_level_db <= C300X_DOOR_LEVEL_MAX_DB
        && door_level_db % C300X_DOOR_LEVEL_STEP_DB == 0
        && fine_gain_db >= C300X_FINE_GAIN_MIN_DB && fine_gain_db <= C300X_FINE_GAIN_MAX_DB;
}

static const char *lever_error(const char *error)
{
    static const char *const known[] = {"hook_foreign", "hook_missing"};
    for (size_t index = 0; index < sizeof(known) / sizeof(known[0]); index++) {
        if (strcmp(error, known[index]) == 0) {
            return known[index];
        }
    }
    return "write_failed";
}

int c300x_audio_level_set(int door_level_db, int fine_gain_db)
{
    char error[48] = "";
    int steps = door_level_db / C300X_DOOR_LEVEL_STEP_DB;
    int supported;
    int applied;
    int current = 0;
    int ours;
    const char *lever;

    if (!c300x_audio_level_valid(door_level_db, fine_gain_db)) {
        return 0;
    }
    ensure_init();
    pthread_mutex_lock(&set_lock);
    supported = c300x_audio_chip_supported();
    /* Stock, or no lever: our hook goes and the stub comes back. */
    applied = c300x_audio_chip_apply(supported ? steps : 0, error, sizeof(error));
    ours = c300x_audio_chip_hook_state(&current) == C300X_AUDIO_HOOK_OURS;
    if (!supported) {
        lever = "unsupported";
    } else if (!applied) {
        lever = lever_error(error);
    } else {
        lever = lever_for(door_level_db, 1, ours && current == steps);
    }
    pthread_mutex_lock(&level_lock);
    level.door_db = door_level_db;
    level.fine_db = fine_gain_db;
    level.hook_ours = ours;
    level.lever = lever;
    /* Without our hook the chip is at the profile's value again. */
    level.chip_db = ours ? level.chip_db : 0;
    level.chip_checked_ms = 0;
    level.generation++;
    rebuild_locked();
    pthread_mutex_unlock(&level_lock);
    pthread_mutex_unlock(&set_lock);
    return 1;
}

static const char *path_locked(void)
{
    if (level.door_db == 0) {
        return "none";
    }
    if (!level.observed) {
        return level.hook_ours ? "chip" : "software";
    }
    if (level.chip_db >= level.door_db) {
        return "chip";
    }
    return level.chip_db > 0 ? "chip_and_software" : "software";
}

size_t c300x_audio_level_json(char *out, size_t out_len)
{
    int written;

    ensure_init();
    pthread_mutex_lock(&level_lock);
    written = snprintf(out, out_len,
        "{\"door_level_db\":%d,\"fine_gain_db\":%d,\"door_level_path\":\"%s\","
        "\"chip_lever\":\"%s\",\"chip_gain_db\":%d,\"software_gain_db\":%d}",
        level.door_db, level.fine_db, path_locked(), level.lever, level.chip_db, level.gain.db);
    pthread_mutex_unlock(&level_lock);
    return written > 0 && (size_t)written < out_len ? (size_t)written : 0;
}

void c300x_audio_level_session_boundary(void)
{
    ensure_init();
    pthread_mutex_lock(&level_lock);
    level.last_audio_ms = 0;
    level.chip_checked_ms = 0;
    level.chip_db = 0;
    level.generation++;
    rebuild_locked();
    pthread_mutex_unlock(&level_lock);
}

/* Reads the chip outside the lock, as often as the start of the sound needs.
 * A set() or boundary meanwhile wins: the result was read with the old state
 * and is dropped; the next packet reads again. */
static void refresh_chip(void)
{
    long long now = c300x_monotonic_ms();
    long long interval;
    int check;
    int ours;
    int chip_db = 0;
    unsigned generation;

    pthread_mutex_lock(&level_lock);
    if (level.last_audio_ms == 0 || now - level.last_audio_ms >= AUDIO_GAP_MS) {
        level.audio_start_ms = now;
        level.chip_checked_ms = 0;
    }
    level.last_audio_ms = now;
    interval = now - level.audio_start_ms < CHIP_START_MS ? CHIP_START_CHECK_MS : CHIP_CHECK_MS;
    check = level.chip_checked_ms == 0 || now - level.chip_checked_ms >= interval;
    if (check) {
        level.chip_checked_ms = now;
    }
    ours = level.hook_ours;
    generation = level.generation;
    pthread_mutex_unlock(&level_lock);
    if (!check) {
        return;
    }
    if (ours && !c300x_audio_chip_current_db(&chip_db)) {
        chip_db = 0;
    }
    pthread_mutex_lock(&level_lock);
    if (generation == level.generation) {
        level.chip_db = chip_db;
        level.observed = 1;
        rebuild_locked();
    }
    pthread_mutex_unlock(&level_lock);
}

void c300x_audio_level_pcmu(unsigned char *data, size_t len, int apply)
{
    if (!apply) {
        return;
    }
    ensure_init();
    refresh_chip();
    pthread_mutex_lock(&level_lock);
    c300x_audio_gain_pcmu(&level.gain, data, len);
    pthread_mutex_unlock(&level_lock);
}

void c300x_audio_level_to_pcmu(const int16_t *samples, unsigned char *out, size_t count, int apply)
{
    if (!apply) {
        for (size_t index = 0; index < count; index++) {
            out[index] = c300x_pcmu_encode(samples[index]);
        }
        return;
    }
    ensure_init();
    refresh_chip();
    pthread_mutex_lock(&level_lock);
    c300x_audio_gain_linear_to_pcmu(&level.gain, samples, out, count);
    pthread_mutex_unlock(&level_lock);
}

int c300x_audio_level_remove_patches(char *error, size_t error_len)
{
    return c300x_audio_chip_remove_patches(error, error_len);
}
