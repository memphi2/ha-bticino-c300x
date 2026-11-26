/* Door level and fine adjustment: the gain curve, the chip hook and the
 * software share. Built with -DSTOCK_HOOK_SHA256/-DIP_PROFILE_SHA256 of the
 * synthetic stand-ins the runner writes; argv[1] is a scratch directory. */
#include "../src/audio_gain.c"
#include "../src/audio_chip.c"
#include "../src/audio_level.c"

#include <assert.h>
#include <sys/stat.h>

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
        int previous = INT16_MIN;
        c300x_audio_gain_init(&gain, db);
        for (int sample = INT16_MIN; sample <= INT16_MAX; sample++) {
            int out = c300x_audio_gain_sample(&gain, (int16_t)sample);
            long long linear = ((long long)sample * gain.q16 + (sample >= 0 ? 32768 : -32768)) / 65536;
            assert(out >= previous);
            assert(out <= LIMIT_CEILING && out >= -LIMIT_CEILING);
            if (linear <= LIMIT_KNEE && linear >= -LIMIT_KNEE) {
                assert(out == linear);
            }
            if (sample > INT16_MIN) {
                assert(c300x_audio_gain_sample(&gain, (int16_t)-sample) == -out);
            }
            previous = out;
        }
        for (int code = 0; code < 256; code++) {
            assert(gain.pcmu[code] == c300x_pcmu_encode(c300x_audio_gain_sample(&gain, c300x_pcmu_decode((unsigned char)code))));
        }
    }
}

static const char stub[] = "#!/bin/bash\ncase \"$1\" in\n*) ;;\nesac\nexit 1\n";

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

    /* Ours without the stub in the backup: nothing else is put back. */
    reset_device();
    assert(c300x_audio_chip_apply(1, error, sizeof(error)));
    put("backup/Audio_State.sh", "#!/bin/sh\nexit 0\n", 0644);
    assert(!c300x_audio_chip_apply(0, error, sizeof(error)) && strcmp(error, "hook_backup_invalid") == 0);
    assert(!c300x_audio_chip_apply(3, error, sizeof(error)) && strcmp(error, "hook_backup_invalid") == 0);
    assert(strstr(get("Audio_State.sh"), "\nV=12\n") != NULL);
    assert(!c300x_audio_chip_remove_patches(error, sizeof(error)));
    put("backup/Audio_State.sh", stub, 0644);
    assert(c300x_audio_chip_remove_patches(error, sizeof(error)));
    assert(strcmp(get("Audio_State.sh"), stub) == 0);
    assert(!c300x_audio_chip_apply(5, error, sizeof(error)));

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
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    level_json_has(json, "\"door_level_path\":\"chip\",\"chip_lever\":\"ready\"");
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

    /* Stock puts the stub back; no lever means the full level in software. */
    assert(c300x_audio_level_set(0, 0));
    assert(strcmp(get("Audio_State.sh"), stub) == 0);
    put("IP_PE.cr", "other\n", 0644);
    assert(c300x_audio_level_set(12, 10));
    assert(strcmp(get("Audio_State.sh"), stub) == 0);
    assert(c300x_audio_level_json(json, sizeof(json)) > 0);
    level_json_has(json, "\"door_level_path\":\"software\",\"chip_lever\":\"unsupported\"");
    level.chip_checked_ms = 0;
    assert(pass(100) == c300x_pcmu_decode(c300x_pcmu_encode(1259)));
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

int main(int argc, char **argv)
{
    char path[640];

    if (argc == 3 && strcmp(argv[1], "render") == 0) {
        char hook[HOOK_MAX];
        assert(c300x_audio_chip_render_hook(atoi(argv[2]), hook, sizeof(hook)) > 0);
        fputs(hook, stdout);
        return 0;
    }
    assert(argc == 2);
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

    test_gain_curve();
    test_chip();
    test_level();
    puts("ok");
    return 0;
}
