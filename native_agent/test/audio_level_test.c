/* Door level and fine adjustment: the gain curve, the chip hook and the
 * software share. Built with -DSTOCK_HOOK_SHA256/-DIP_PROFILE_SHA256 of the
 * synthetic stand-ins the runner writes; argv[1] is a scratch directory. */
#include <assert.h>

#include "../src/audio_gain.c"
#include "../src/audio_chip.c"
/* The chip read of audio_level.c, with a set() that can come in while it
 * runs outside the lock. */
int chip_read_racing(int *db);
long long test_clock(void);
#define c300x_audio_chip_current_db chip_read_racing
#define c300x_monotonic_ms test_clock
#include "../src/audio_level.c"
#undef c300x_monotonic_ms
#undef c300x_audio_chip_current_db

static long long clock_ms = 1000000;
long long test_clock(void) { return clock_ms; }

#include <sys/stat.h>

static int race_door_db = -1;

int chip_read_racing(int *db)
{
    int ok = c300x_audio_chip_current_db(db);
    if (race_door_db >= 0) {
        int door = race_door_db;
        race_door_db = -1;
        assert(c300x_audio_level_set(door, 0));
    }
    return ok;
}

static int model = C300X_DEVICE_MODEL_C300X;
enum c300x_device_model c300x_device_model(void) { return (enum c300x_device_model)model; }

static char dir[512];

static void path_of(char *out, size_t len, const char *name)
{
    assert((size_t)snprintf(out, len, "%s/%s", dir, name) < len);
}

static void put(const char *name, const char *text, mode_t mode)
{
    char path[640];
    FILE *fp;
    path_of(path, sizeof(path), name);
    fp = fopen(path, "w");
    assert(fp != NULL && fputs(text, fp) >= 0 && fclose(fp) == 0);
    assert(chmod(path, mode) == 0);
}

static char *get(const char *name)
{
    static char data[4096];
    char path[640];
    size_t got;
    FILE *fp;
    path_of(path, sizeof(path), name);
    fp = fopen(path, "r");
    if (fp == NULL) {
        return NULL;
    }
    got = fread(data, 1, sizeof(data) - 1, fp);
    data[got] = '\0';
    fclose(fp);
    return data;
}

static int exists(const char *name)
{
    char path[640];
    path_of(path, sizeof(path), name);
    return access(path, F_OK) == 0;
}

static void drop(const char *name)
{
    char path[640];
    path_of(path, sizeof(path), name);
    (void)unlink(path);
}

static void env(const char *key, const char *name)
{
    char path[640];
    path_of(path, sizeof(path), name);
    assert(setenv(key, path, 1) == 0);
}

static void test_gain_curve(void)
{
    struct c300x_audio_gain gain;

    c300x_audio_gain_init(&gain, 0);
    for (int code = 0; code < 256; code++) {
        unsigned char value = (unsigned char)code;
        c300x_audio_gain_pcmu(&gain, &value, 1);
        assert(value == code);
    }
    for (int sample = INT16_MIN; sample <= INT16_MAX; sample += 7) {
        unsigned char out;
        int16_t in = (int16_t)sample;
        c300x_audio_gain_linear_to_pcmu(&gain, &in, &out, 1);
        assert(out == c300x_pcmu_encode(in));
    }

    c300x_audio_gain_init(&gain, 6);
    assert(c300x_audio_gain_sample(&gain, 1000) == 1995);
    assert(c300x_audio_gain_sample(&gain, -1000) == -1995);
    assert(c300x_audio_gain_sample(&gain, 8000) == 15962);
    c300x_audio_gain_init(&gain, -6);
    assert(c300x_audio_gain_sample(&gain, 32767) == 16422);
    assert(c300x_audio_gain_sample(&gain, INT16_MIN) == -16423);
    c300x_audio_gain_init(&gain, 99);
    assert(gain.db == C300X_AUDIO_GAIN_MAX_DB);
    c300x_audio_gain_init(&gain, -99);
    assert(gain.db == C300X_AUDIO_GAIN_MIN_DB);

    /* The limiter: linear to -6 dBFS, monotonic, never past the ceiling,
     * symmetric; the PCMU table is the same curve. */
    for (int db = 1; db <= C300X_AUDIO_GAIN_MAX_DB; db++) {
        c300x_audio_gain_init(&gain, db);
        for (int sample = INT16_MIN; sample <= INT16_MAX; sample++) {
            int out = c300x_audio_gain_sample(&gain, (int16_t)sample);
            long long linear = ((long long)sample * gain.q16 + (sample >= 0 ? 32768 : -32768)) / 65536;
            if (linear <= LIMIT_KNEE && linear >= -LIMIT_KNEE) {
                assert(out == linear);
            }
            if (sample > INT16_MIN) {
                assert(c300x_audio_gain_sample(&gain, (int16_t)-sample) == -out);
            }
        }
        for (int code = 0; code < 256; code++) {
            assert(gain.pcmu[code] == c300x_pcmu_encode(c300x_audio_gain_sample(&gain, c300x_pcmu_decode((unsigned char)code))));
        }
    }
}

/* Every gain, every sample: monotonic, a gain above 0 dB never makes a sample
 * quieter and one below never louder, louder gains never give less, nothing
 * past the ceiling that was not there already, and 0 dB passes unchanged. */
static void test_gain_bounds(void)
{
    static int16_t below[65536];
    struct c300x_audio_gain gain;

    for (int db = C300X_AUDIO_GAIN_MIN_DB; db <= C300X_AUDIO_GAIN_MAX_DB; db++) {
        int previous = INT16_MIN;
        c300x_audio_gain_init(&gain, db);
        for (int sample = INT16_MIN; sample <= INT16_MAX; sample++) {
            int out = c300x_audio_gain_sample(&gain, (int16_t)sample);
            int in_mag = abs(sample);
            int out_mag = abs(out);
            int16_t *last = &below[sample - INT16_MIN];
            assert(out >= previous);
            assert(out == 0 || sample == 0 || (out < 0) == (sample < 0));
            if (db == 0) {
                assert(out == sample);
            } else if (db > 0) {
                assert(out_mag >= in_mag);
                assert(out_mag <= (in_mag > LIMIT_CEILING ? in_mag : LIMIT_CEILING));
                assert(out_mag >= abs(*last));
            } else {
                assert(out_mag <= in_mag);
            }
            if (db >= 0) {
                *last = (int16_t)out;
            }
            previous = out;
        }
    }
    /* The loud peaks the old knee bent below their input. */
    c300x_audio_gain_init(&gain, 3);
    assert(c300x_audio_gain_sample(&gain, 27004) >= 27004);
    c300x_audio_gain_init(&gain, 1);
    assert(c300x_audio_gain_sample(&gain, INT16_MAX) == INT16_MAX);
}

static const char stub[] = "#!/bin/bash\ncase \"$1\" in\n*) ;;\nesac\nexit 1\n";
/* What a lost backup gives back. */
static const char neutral[] = "#!/bin/sh\nexit 1\n";

static void reset_device(void)
{
    put("Audio_State.sh", stub, 0775);
    drop("backup/Audio_State.sh");
    drop("mark");
    put("sout", "11\n", 0644);
}

static void test_chip(void)
{
    char error[64] = "";
    char hook[HOOK_MAX];
    int steps = -1;
    int db = -1;
    struct stat st;
    char path[640];

    reset_device();
    assert(c300x_audio_chip_supported());
    assert(c300x_audio_chip_hook_state(&steps) == C300X_AUDIO_HOOK_STOCK && steps == 0);

    /* +6 dB: the stub goes to the backup, the hook carries 13. */
    assert(c300x_audio_chip_apply(2, error, sizeof(error)));
    assert(c300x_audio_chip_hook_state(&steps) == C300X_AUDIO_HOOK_OURS && steps == 2);
    assert(strstr(get("Audio_State.sh"), "\nV=13\n") != NULL);
    assert(strcmp(get("backup/Audio_State.sh"), stub) == 0);
    path_of(path, sizeof(path), "Audio_State.sh");
    assert(stat(path, &st) == 0 && (st.st_mode & 0777) == 0775);
    assert(c300x_audio_chip_apply(4, error, sizeof(error)));
    assert(strstr(get("Audio_State.sh"), "\nV=15\n") != NULL);
    assert(strcmp(get("backup/Audio_State.sh"), stub) == 0);
    assert(c300x_audio_chip_render_hook(4, hook, sizeof(hook)) == strlen(get("Audio_State.sh")));

    /* What the chip adds: only with the hook's mark, from the live value. */
    assert(c300x_audio_chip_current_db(&db) && db == 0);
    put("mark", "15\n", 0644);
    put("sout", "15\n", 0644);
    assert(c300x_audio_chip_current_db(&db) && db == 12);
    put("sout", "13\n", 0644);
    assert(c300x_audio_chip_current_db(&db) && db == 6);
    put("sout", "x\n", 0644);
    assert(c300x_audio_chip_current_db(&db) && db == 12);
    put("mark", "junk\n", 0644);
    assert(!c300x_audio_chip_current_db(&db) && db == 0);
    /* A mark that exists but does not parse (empty, half written): the live
     * value tells what the chip adds. */
    put("sout", "13\n", 0644);
    put("mark", "", 0644);
    assert(c300x_audio_chip_current_db(&db) && db == 6);
    put("mark", "junk\n", 0644);
    assert(c300x_audio_chip_current_db(&db) && db == 6);
    put("sout", "11\n", 0644);
    assert(c300x_audio_chip_current_db(&db) && db == 0);

    /* Stock: the stub comes back and a raised call is lowered now. */
    put("mark", "15\n", 0644);
    put("sout", "15\n", 0644);
    assert(c300x_audio_chip_apply(0, error, sizeof(error)));
    assert(strcmp(get("Audio_State.sh"), stub) == 0);
    assert(atoi(get("sout")) == 11 && !exists("mark"));
    assert(c300x_audio_chip_apply(0, error, sizeof(error)));

    /* Somebody else's hook is never touched. */
    put("Audio_State.sh", "#!/bin/sh\necho mine\n", 0755);
    assert(!c300x_audio_chip_apply(2, error, sizeof(error)) && strcmp(error, "hook_foreign") == 0);
    assert(strcmp(get("Audio_State.sh"), "#!/bin/sh\necho mine\n") == 0);
    assert(c300x_audio_chip_apply(0, error, sizeof(error)));
    assert(strcmp(get("Audio_State.sh"), "#!/bin/sh\necho mine\n") == 0);

    /* Ours without the stub in the backup: the backup is never put back,
     * the neutral stub is, with the file's mode; it counts as stock. */
    reset_device();
    assert(c300x_audio_chip_apply(1, error, sizeof(error)));
    put("backup/Audio_State.sh", "#!/bin/sh\nexit 0\n", 0644);
    assert(c300x_audio_chip_apply(3, error, sizeof(error)));
    assert(strstr(get("Audio_State.sh"), "\nV=14\n") != NULL);
    put("mark", "14\n", 0644);
    put("sout", "14\n", 0644);
    assert(c300x_audio_chip_apply(0, error, sizeof(error)));
    assert(strcmp(get("Audio_State.sh"), neutral) == 0);
    assert(stat(path, &st) == 0 && (st.st_mode & 0777) == 0775);
    assert(atoi(get("sout")) == 11 && !exists("mark"));
    assert(c300x_audio_chip_hook_state(&steps) == C300X_AUDIO_HOOK_STOCK);
    /* From the neutral stub: installed and put back like the vendor's. */
    assert(c300x_audio_chip_apply(2, error, sizeof(error)));
    assert(strcmp(get("backup/Audio_State.sh"), neutral) == 0);
    assert(c300x_audio_chip_remove_patches(error, sizeof(error)));
    assert(strcmp(get("Audio_State.sh"), neutral) == 0);
    /* No backup at all. */
    assert(c300x_audio_chip_apply(2, error, sizeof(error)));
    drop("backup/Audio_State.sh");
    assert(c300x_audio_chip_remove_patches(error, sizeof(error)));
    assert(strcmp(get("Audio_State.sh"), neutral) == 0);
    assert(stat(path, &st) == 0 && (st.st_mode & 0777) == 0775);
    assert(!c300x_audio_chip_apply(5, error, sizeof(error)));

    /* A hook of ours from another agent version: known by its marker line,
     * its level read from V=, rewritten to this version's template and put
     * back to the stub like any of ours. */
    reset_device();
    assert(c300x_audio_chip_apply(2, error, sizeof(error)));
    put("Audio_State.sh", "#!/bin/sh\n# c300x-agent audio hook v0\nV=13\nexit 1\n", 0775);
    assert(c300x_audio_chip_hook_state(&steps) == C300X_AUDIO_HOOK_OURS && steps == 2);
    assert(c300x_audio_chip_apply(2, error, sizeof(error)));
    assert(c300x_audio_chip_render_hook(2, hook, sizeof(hook)) > 0 && strcmp(get("Audio_State.sh"), hook) == 0);
    put("Audio_State.sh", "#!/bin/sh\n# c300x-agent audio hook v9\nV=x\nexit 1\n", 0775);
    assert(c300x_audio_chip_hook_state(&steps) == C300X_AUDIO_HOOK_OURS && steps == 0);
    assert(c300x_audio_chip_remove_patches(error, sizeof(error)));
    assert(strcmp(get("Audio_State.sh"), stub) == 0);
    /* The marker alone in a file that is not a script is not ours. */
    put("Audio_State.sh", "echo\n# c300x-agent audio hook v1\nV=13\n", 0775);
    assert(c300x_audio_chip_hook_state(&steps) == C300X_AUDIO_HOOK_FOREIGN);
    put("Audio_State.sh", stub, 0775);

    /* No lever on another model, another profile or without amixer. */
    model = C300X_DEVICE_MODEL_C100X;
    assert(!c300x_audio_chip_supported());
    model = C300X_DEVICE_MODEL_C300X;
    put("IP_PE.cr", "other\n", 0644);
    assert(!c300x_audio_chip_supported());
    put("IP_PE.cr", "profile\n", 0644);
    put("amixer", "#!/bin/sh\n", 0644);
    assert(!c300x_audio_chip_supported());
    put("amixer", "#!/bin/sh\n", 0755);
    drop("sout");
    assert(!c300x_audio_chip_supported());
    put("sout", "11\n", 0644);
    assert(c300x_audio_chip_supported());
}

static int level_json_int(const char *json, const char *field)
{
    char key[64];
    const char *at;
    snprintf(key, sizeof(key), "\"%s\":", field);
    at = strstr(json, key);
    assert(at != NULL);
    return atoi(at + strlen(key));
}

static void level_json_has(const char *json, const char *text)
{
    if (strstr(json, text) == NULL) {
        fprintf(stderr, "%s lacks %s\n", json, text);
        assert(0);
    }
}

static int16_t pass(int16_t sample)
{
    unsigned char out;
    c300x_audio_level_to_pcmu(&sample, &out, 1, 1);
    return c300x_pcmu_decode(out);
}

static void test_level(void)
{
    char json[C300X_AUDIO_LEVEL_JSON_MAX];
    unsigned char pcmu[160];

    reset_device();
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    level_json_has(json, "\"door_level_db\":0,\"fine_gain_db\":0,\"door_level_path\":\"none\",\"chip_lever\":\"off\"");

    assert(!c300x_audio_level_set(5, 0) && !c300x_audio_level_set(15, 0) && !c300x_audio_level_set(-3, 0));
    assert(!c300x_audio_level_set(6, 11) && !c300x_audio_level_set(6, -11));

    /* The chip carries +6 during a raised call; the software stage adds only
     * the fine adjustment then. */
    assert(c300x_audio_level_set(6, -2));
    assert(strstr(get("Audio_State.sh"), "\nV=13\n") != NULL);
    /* No call yet: path and both gains say nothing is applied, and agree. */
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    level_json_has(json, "\"door_level_path\":\"none\",\"chip_lever\":\"ready\",\"chip_gain_db\":0,\"software_gain_db\":0");
    put("mark", "13\n", 0644);
    put("sout", "13\n", 0644);
    assert(pass(1000) == c300x_pcmu_decode(c300x_pcmu_encode(794)));
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    assert(level_json_int(json, "chip_gain_db") == 6 && level_json_int(json, "software_gain_db") == -2);
    level_json_has(json, "\"door_level_path\":\"chip\"");

    /* Outside the raised state the door level goes to software. */
    drop("mark");
    level.chip_checked_ms = 0;
    assert(pass(1000) == c300x_pcmu_decode(c300x_pcmu_encode(1585)));
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    assert(level_json_int(json, "chip_gain_db") == 0 && level_json_int(json, "software_gain_db") == 4);
    level_json_has(json, "\"door_level_path\":\"software\"");

    /* The call ends (session boundary, or a second without packets): idle
     * again, whatever the chip did last. */
    put("mark", "13\n", 0644);
    level.chip_checked_ms = 0;
    assert(pass(1000) == c300x_pcmu_decode(c300x_pcmu_encode(794)));
    c300x_audio_level_session_boundary();
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    level_json_has(json, "\"door_level_path\":\"none\",\"chip_lever\":\"ready\",\"chip_gain_db\":0,\"software_gain_db\":0");
    assert(pass(1000) == c300x_pcmu_decode(c300x_pcmu_encode(794)));
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    level_json_has(json, "\"door_level_path\":\"chip\",\"chip_lever\":\"ready\",\"chip_gain_db\":6,\"software_gain_db\":-2");
    clock_ms += 999;
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    level_json_has(json, "\"door_level_path\":\"chip\"");
    clock_ms += 1;
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    level_json_has(json, "\"door_level_path\":\"none\",\"chip_lever\":\"ready\",\"chip_gain_db\":0,\"software_gain_db\":0");
    drop("mark");
    put("sout", "11\n", 0644);

    /* A level lowered during a raised call: the software stage takes the
     * difference back until the next state change. */
    put("mark", "15\n", 0644);
    put("sout", "15\n", 0644);
    assert(c300x_audio_level_set(6, 0));
    assert(pass(2000) == c300x_pcmu_decode(c300x_pcmu_encode(1002)));
    assert(level.gain.db == -6);

    /* Within the check interval the chip is not read again. */
    put("sout", "11\n", 0644);
    assert(pass(2000) == c300x_pcmu_decode(c300x_pcmu_encode(1002)));

    /* PCMU through the table, and an untouched copy for calls with the home. */
    level.chip_checked_ms = 0;
    for (size_t index = 0; index < sizeof(pcmu); index++) {
        pcmu[index] = (unsigned char)index;
    }
    c300x_audio_level_pcmu(pcmu, sizeof(pcmu), 0);
    for (size_t index = 0; index < sizeof(pcmu); index++) {
        assert(pcmu[index] == index);
    }
    c300x_audio_level_pcmu(pcmu, sizeof(pcmu), 1);
    for (size_t index = 0; index < sizeof(pcmu); index++) {
        assert(pcmu[index] == level.gain.pcmu[index]);
    }

    /* A set() while a chip read runs: the read was made with the old hook
     * and never lands; the packet gets the new level at once. */
    put("mark", "15\n", 0644);
    put("sout", "15\n", 0644);
    assert(c300x_audio_level_set(12, 0));
    assert(pass(1000) == c300x_pcmu_decode(c300x_pcmu_encode(1000)) && level.chip_db == 12);
    level.chip_checked_ms = 0;
    race_door_db = 0;
    assert(pass(1000) == c300x_pcmu_decode(c300x_pcmu_encode(1000)));
    assert(race_door_db == -1 && level.chip_db == 0 && level.gain.db == 0);
    assert(atoi(get("sout")) == 11 && !exists("mark"));

    /* Stock puts the stub back; no lever means the full level in software. */
    assert(c300x_audio_level_set(0, 0));
    assert(strcmp(get("Audio_State.sh"), stub) == 0);
    put("IP_PE.cr", "other\n", 0644);
    assert(c300x_audio_level_set(12, 10));
    assert(strcmp(get("Audio_State.sh"), stub) == 0);
    level.chip_checked_ms = 0;
    assert(pass(100) == c300x_pcmu_decode(c300x_pcmu_encode(1259)));
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    level_json_has(json, "\"door_level_path\":\"software\",\"chip_lever\":\"unsupported\"");
    assert(level_json_int(json, "software_gain_db") == 22);
    put("IP_PE.cr", "profile\n", 0644);

    /* A foreign hook: the level still applies, in software. */
    put("Audio_State.sh", "#!/bin/sh\necho mine\n", 0755);
    assert(c300x_audio_level_set(9, 0));
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    level_json_has(json, "\"chip_lever\":\"hook_foreign\"");
    level.chip_checked_ms = 0;
    put("mark", "15\n", 0644);
    assert(pass(1000) == c300x_pcmu_decode(c300x_pcmu_encode(2818)));
}

/* One door call at +6 dB with the chip lever: packets every step ms from
 * the start, the hook marks and raises the chip at raise_at ms (the gain lag
 * ms after the mark) and, with lower_at >= 0, lowers it again then (OFF).
 * Returns how many packets after a change still carried the old software
 * share; *window gets the longest time from a change to the first packet
 * with the right share. */
static int call_late_packets(int step, int raise_at, int lag, int lower_at, int boundary, long long *window)
{
    const int16_t full = c300x_pcmu_decode(c300x_pcmu_encode(1995));
    const int16_t chip = c300x_pcmu_decode(c300x_pcmu_encode(1000));
    long long changed = -1;
    long long start;
    int raised = 0;
    int marked = 0;
    int late = 0;

    *window = 0;
    if (boundary) {
        c300x_audio_level_session_boundary();
    }
    start = clock_ms;
    for (int at = 0; at <= 3000; at += step) {
        clock_ms = start + at;
        if (!marked && at >= raise_at) {
            put("mark", "13\n", 0644);
            marked = 1;
        }
        if (!raised && marked && at >= raise_at + lag && (lower_at < 0 || at < lower_at)) {
            put("sout", "13\n", 0644);
            raised = 1;
            changed = start + raise_at + lag;
        }
        if (raised && lower_at >= 0 && at >= lower_at) {
            put("sout", "11\n", 0644);
            drop("mark");
            raised = 0;
            marked = 2;
            changed = start + lower_at;
        }
        if (pass(1000) == (raised ? chip : full)) {
            if (changed >= 0 && clock_ms - changed > *window) {
                *window = clock_ms - changed;
            }
            changed = -1;
        } else {
            late++;
        }
    }
    clock_ms += 1000;
    return late;
}

/* When the HAL runs the hook against the packets: no packet gets the door
 * level twice or not at all at the start of a call, back to back or not. */
static void test_timing(void)
{
    long long window;
    long long worst = 0;
    int late;

    reset_device();
    assert(c300x_audio_level_set(6, 0));
    clock_ms += 1000;
    /* Packets 20 ms apart: the first packet after the raise, at any moment
     * in the first 2 s, has the chip's share. */
    for (int raise_at = 0; raise_at <= 1980; raise_at += 3) {
        assert(call_late_packets(20, raise_at, 0, -1, raise_at % 2, &window) == 0);
        worst = window > worst ? window : worst;
        drop("mark");
        put("sout", "11\n", 0644);
    }
    assert(worst <= 20);
    fprintf(stderr, "start window, 20 ms packets: %lld ms\n", worst);
    /* Bursts 5 ms apart: at most one look per 10 ms, so one packet late. */
    worst = 0;
    for (int raise_at = 0; raise_at <= 1980; raise_at += 7) {
        assert(call_late_packets(5, raise_at, 3, -1, 0, &window) <= 1);
        worst = window > worst ? window : worst;
        drop("mark");
        put("sout", "11\n", 0644);
    }
    assert(worst <= 10);
    fprintf(stderr, "start window, 5 ms packets: %lld ms\n", worst);
    /* The mark comes before the raise: in between nothing is counted twice. */
    assert(call_late_packets(20, 100, 60, -1, 1, &window) == 0);
    drop("mark");
    put("sout", "11\n", 0644);

    /* A lowering during the first 2 s (the HAL leaves the state). */
    assert(call_late_packets(20, 0, 0, 1500, 1, &window) == 0 && window <= 20);

    /* Back to back: a call raised to its end, the HAL lowers the chip (OFF)
     * and the next call starts 30 ms later with a session boundary: its first
     * packet has the full share, nothing of the last call's chip is left. */
    assert(call_late_packets(20, 0, 0, -1, 1, &window) == 0);
    clock_ms -= 1000 - 30;
    drop("mark");
    put("sout", "11\n", 0644);
    assert(call_late_packets(20, 400, 0, -1, 1, &window) == 0 && window <= 20);
    /* Without a boundary, a pause of AUDIO_GAP_MS (100 ms) does the same. */
    clock_ms -= 1000 - 100;
    drop("mark");
    put("sout", "11\n", 0644);
    assert(call_late_packets(20, 300, 0, -1, 0, &window) == 0 && window <= 20);
    drop("mark");
    put("sout", "11\n", 0644);
    /* Later in a call the reads are every 500 ms: the window there. */
    late = call_late_packets(20, 2500, 0, -1, 0, &window);
    assert(late <= 25 && window <= 500);
    fprintf(stderr, "after 2 s: %d packets, %lld ms\n", late, window);
    drop("mark");
    put("sout", "11\n", 0644);
}

int main(int argc, char **argv)
{
    char path[640];

    if (argc == 3 && strcmp(argv[1], "render") == 0) {
        char hook[HOOK_MAX];
        assert(c300x_audio_chip_render_hook(atoi(argv[2]), hook, sizeof(hook)) > 0);
        fputs(hook, stdout);
        return 0;
    }
    assert(argc == 3);
    snprintf(dir, sizeof(dir), "%s", argv[1]);
    path_of(path, sizeof(path), "backup");
    assert(mkdir(path, 0700) == 0);
    env("C300X_AUDIO_BACKUP_DIR", "backup");
    env("C300X_AUDIO_STATE_HOOK", "Audio_State.sh");
    env("C300X_SOUT_MARK", "mark");
    env("C300X_SOUT_GAIN_FILE", "sout");
    env("C300X_ZL_IP_PROFILE", "IP_PE.cr");
    env("C300X_AMIXER", "amixer");
    assert(setenv("C300X_AUDIO_NO_REMOUNT", "1", 1) == 0);
    put("IP_PE.cr", "profile\n", 0644);
    put("amixer", "#!/bin/sh\n", 0755);

    if (strcmp(argv[2], "gain") == 0) {
        test_gain_curve();
    } else if (strcmp(argv[2], "gain_bounds") == 0) {
        test_gain_bounds();
    } else if (strcmp(argv[2], "chip") == 0) {
        test_chip();
    } else if (strcmp(argv[2], "level") == 0) {
        test_level();
    } else if (strcmp(argv[2], "timing") == 0) {
        test_timing();
    } else {
        return 2;
    }
    puts("ok");
    return 0;
}
