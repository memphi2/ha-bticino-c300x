#include <stdio.h>
#include <sys/types.h>
static int checked_mkstemp(char *path);
static FILE *checked_fdopen(int fd, const char *mode);
static int checked_fchown(int fd, uid_t uid, gid_t gid);
#define mkstemp checked_mkstemp
#define fdopen checked_fdopen
#define fchown checked_fchown
#include "../src/config.c"
#undef mkstemp
#undef fdopen
#undef fchown
#include <assert.h>
#include <dirent.h>

static int created;
static int fail_owner;
extern int mkstemp(char *);
extern FILE *fdopen(int, const char *);
extern int fchown(int, uid_t, gid_t);

static int checked_mkstemp(char *path)
{
    int fd = mkstemp(path);
    assert(fd >= 0);
    struct stat status;
    assert(fstat(fd, &status) == 0);
    assert((status.st_mode & 0777) == 0600);
    created++;
    return fd;
}

static FILE *checked_fdopen(int fd, const char *mode)
{
    struct stat status;
    assert(fstat(fd, &status) == 0);
    assert((status.st_mode & 0777) == 0600);
    assert(fcntl(fd, F_GETFD) & FD_CLOEXEC);
    return fdopen(fd, mode);
}

static int checked_fchown(int fd, uid_t uid, gid_t gid)
{
    if (fail_owner) {
        errno = EPERM;
        return -1;
    }
    return fchown(fd, uid, gid);
}

static void decode(const char *json, const char *expected)
{
    char result[256];
    const char *after = NULL;
    assert(c300x_json_decode_string(json, json + strlen(json), result, sizeof(result), &after));
    assert(after == json + strlen(json));
    assert(strcmp(result, expected) == 0);
}

static void invalid(const char *json)
{
    char result[256] = "sentinel";
    assert(!c300x_json_decode_string(json, json + strlen(json), result, sizeof(result), NULL));
    assert(result[0] == '\0');
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    decode("\"M\\u00fcnchen\"", "M\xc3\xbcnchen");
    decode("\"\\uD83D\\uDCA1\"", "\xf0\x9f\x92\xa1");
    decode("\"\\\"\\\\\\/\\b\\f\\n\\r\\t\"", "\"\\/\b\f\n\r\t");
    decode("\"\xc3\xab\"", "\xc3\xab");
    invalid("\"\\u0000\"");
    invalid("\"\\uD800\"");
    invalid("\"\\uDC00\"");
    invalid("\"\\uD800\\u0041\"");
    invalid("\"\\u12xz\"");
    invalid("\"\\x41\"");
    invalid("\"abc\\");
    invalid("\"a\nb\"");
    invalid("\"\xc0\x80\"");
    invalid("\"\xed\xa0\x80\"");
    invalid("\"\xf4\x90\x80\x80\"");
    char small[4];
    assert(!c300x_json_decode_string("\"abcd\"", "\"abcd\"" + 6, small, sizeof(small), NULL));
    assert(small[0] == '\0');
    assert(c300x_json_object_valid("{\"x\":[true,false,null,-1.25e+2,{\"a\":\"b\"}]}"));
    const char *bad[] = {"{\"a\":trueX}", "{\"a\":01}", "{\"a\":1,}", "{} garbage",
        "{\"a\":[1,]}", "{\"a\":\"\\u0000\"}", "{\"a\":\"\\uD800\"}", "[]"};
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        assert(!c300x_json_object_valid(bad[i]));
    }
    char nested[256];
    memset(nested, '[', 100);
    memset(nested + 100, ']', 100);
    nested[200] = '\0';
    assert(c300x_json_skip_value(nested, nested + 200) == NULL);
    int number = 7;
    assert(!c300x_json_bool_field("{\"value\":\"enabled\",\"other\":true}", "enabled", &number));
    assert(!c300x_json_bool_field("{\"nested\":{\"enabled\":true}}", "enabled", &number));
    assert(c300x_json_bool_field("{\"en\\u0061bled\":false}", "enabled", &number) && number == 0);
    assert(!c300x_json_int_field("{\"port\":4294967297}", "port", &number));
    assert(!c300x_json_int_field("{\"port\":1.5}", "port", &number));
    assert(!c300x_json_int_field("{\"port\":1junk}", "port", &number));

    struct c300x_config *config = calloc(1, sizeof(*config));
    struct c300x_config *loaded = calloc(1, sizeof(*loaded));
    assert(config && loaded);
    c300x_default_config(config);
    const char *activation = "{\"id\":\"command-only\",\"name\":\"Custom\",\"pressCommand\":\"*1*1*11##\"}";
    char activation_error[256];
    assert(parse_activation_item(activation, activation + strlen(activation),
                                &config->activations[0], activation_error, sizeof(activation_error)));
    config->activations_count = 1;
    snprintf(config->config_path, sizeof(config->config_path), "%s/config.json", argv[1]);
    snprintf(config->api_token, sizeof(config->api_token), "synthetic-api");
    snprintf(config->mqtt_password, sizeof(config->mqtt_password), "s\xc3\xab" "cret\n\\\"");
    snprintf(config->lock_name, sizeof(config->lock_name), "Door \xf0\x9f\x92\xa1");
    char error[256], trap[C300X_MAX_PATH_LEN + 8];
    snprintf(trap, sizeof(trap), "%s.tmp", config->config_path);
    assert(symlink("victim", trap) == 0);
    char victim[C300X_MAX_PATH_LEN];
    snprintf(victim, sizeof(victim), "%s/victim", argv[1]);
    FILE *file = fopen(victim, "w");
    assert(file && fputs("untouched", file) >= 0 && fclose(file) == 0);
    mode_t previous = umask(0);
    int changed = 0;
    assert(c300x_save_config_if_changed(config, error, sizeof(error), &changed));
    assert(changed && created == 1);
    umask(previous);
    struct stat before, after;
    assert(stat(config->config_path, &before) == 0);
    assert((before.st_mode & 0777) == 0600);
    assert(c300x_load_config(config->config_path, loaded, error, sizeof(error)));
    assert(loaded->activations_count == 1);
    assert(loaded->activations[0].address[0] == '\0');
    assert(strcmp(loaded->activations[0].press_command, "*1*1*11##") == 0);
    assert(strcmp(loaded->mqtt_password, config->mqtt_password) == 0);
    assert(strcmp(loaded->lock_name, config->lock_name) == 0);
    assert(c300x_save_config_if_changed(config, error, sizeof(error), &changed) && !changed);
    assert(stat(config->config_path, &after) == 0 && before.st_ino == after.st_ino);
    assert(chmod(config->config_path, 0644) == 0);
    assert(c300x_save_config_if_changed(config, error, sizeof(error), &changed) && changed);
    assert(stat(config->config_path, &after) == 0 && (after.st_mode & 0777) == 0600);
    strcpy(config->mqtt_password, "replacement");
    fail_owner = 1;
    assert(!c300x_save_config_if_changed(config, error, sizeof(error), &changed));
    assert(stat(config->config_path, &after) == 0 && before.st_ino == after.st_ino);
    fail_owner = 0;
    assert(c300x_save_config_if_changed(config, error, sizeof(error), &changed) && changed);
    assert(stat(config->config_path, &after) == 0);
    assert(after.st_uid == before.st_uid && after.st_gid == before.st_gid);
    file = fopen(victim, "r");
    char content[32];
    assert(file && fgets(content, sizeof(content), file) && fclose(file) == 0);
    assert(strcmp(content, "untouched") == 0);
    DIR *directory = opendir(argv[1]);
    assert(directory);
    struct dirent *entry;
    while ((entry = readdir(directory))) {
        assert(strncmp(entry->d_name, "config.json.tmp.", 16) != 0);
    }
    closedir(directory);
    config->api_port = 19090;
    assert(c300x_save_config_if_changed(config, error, sizeof(error), &changed));
    config->api_port = 18090;
    config->restart_required = 1;
    assert(c300x_normalize_config(config, error, sizeof(error), &changed));
    assert(c300x_load_config(config->config_path, loaded, error, sizeof(error)));
    assert(loaded->api_port == 19090);
    *loaded = *config;
    strcpy(loaded->mqtt_username, "updated-user");
    assert(c300x_save_mqtt_config(config, loaded, error, sizeof(error), &changed));
    assert(c300x_load_config(config->config_path, loaded, error, sizeof(error)));
    assert(loaded->api_port == 19090);
    assert(strcmp(loaded->mqtt_username, "updated-user") == 0);
    assert(config->api_port == 18090 && config->restart_required);
    *loaded = *config;
    assert(c300x_config_listen_valid(loaded, error, sizeof(error)));
    strcpy(loaded->listen_host, "localhost");
    assert(!c300x_config_listen_valid(loaded, error, sizeof(error)));
    strcpy(loaded->listen_host, "127.0.0.1");
    loaded->ui_port = loaded->api_port;
    assert(!c300x_config_listen_valid(loaded, error, sizeof(error)));
    loaded->ui_port = 18091;
    loaded->video_enabled = 1;
    loaded->video_rtsp_port = loaded->ui_port;
    assert(!c300x_config_listen_valid(loaded, error, sizeof(error)));
    *loaded = *config;
    strcpy(loaded->listen_host, "localhost");
    loaded->allow_lan = 1;
    assert(c300x_save_config_if_changed(loaded, error, sizeof(error), &changed));
    assert(!c300x_load_config(config->config_path, loaded, error, sizeof(error)));
    assert(strstr(error, "listen.host") != NULL);
    free(config);
    free(loaded);
    return 0;
}
