#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#include "activation_discovery.h"

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <sys/stat.h>
#include <unistd.h>

#define C300X_DISCOVERY_MAX_DEPTH 2
#define C300X_DISCOVERY_MAX_FILES 64
#define C300X_DISCOVERY_MAX_FILE_BYTES 65536
#define C300X_DISCOVERY_CONTEXT_BYTES 512

#ifdef __arm__
#define C300X_DISCOVERY_STAT_STRUCT struct stat64
#else
#define C300X_DISCOVERY_STAT_STRUCT struct stat
#endif

static int stat_path(const char *path, C300X_DISCOVERY_STAT_STRUCT *status)
{
#ifdef __arm__
    return (int)syscall(SYS_stat64, path, status);
#else
    return stat(path, status);
#endif
}

static void safe_copy(char *dest, size_t dest_len, const char *value)
{
    if (dest_len == 0) {
        return;
    }
    snprintf(dest, dest_len, "%s", value != NULL ? value : "");
}

static int address_is_valid(const char *value)
{
    size_t len = strlen(value);

    if (len == 0 || len >= C300X_MAX_ADDRESS_LEN) {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        if (!isdigit((unsigned char)value[index]) && value[index] != '#') {
            return 0;
        }
    }
    return 1;
}

static int frame_is_valid(const char *value)
{
    size_t len = strlen(value);

    if (len < 3 || len >= C300X_MAX_FRAME_LEN || value[0] != '*') {
        return 0;
    }
    if (value[len - 1] != '#' || value[len - 2] != '#') {
        return 0;
    }
    for (size_t index = 0; index < len; index++) {
        if (!isdigit((unsigned char)value[index])
            && value[index] != '*'
            && value[index] != '#') {
            return 0;
        }
    }
    return 1;
}

static int path_contains(const char *path, const char *needle)
{
    return path != NULL && needle != NULL && strstr(path, needle) != NULL;
}

static int discovery_path_allowed(const char *path)
{
    if (path_contains(path, "c300x-native-agent")
        || path_contains(path, "c300x-device-file-backups")
        || path_contains(path, "/.git/")
        || path_contains(path, "/node_modules/")
        || path_contains(path, "/__pycache__/")) {
        return 0;
    }
    return 1;
}

static int basename_has_activation_hint(const char *path)
{
    const char *base = strrchr(path, '/');
    char lower[C300X_MAX_PATH_LEN];
    size_t len;

    base = base != NULL ? base + 1 : path;
    len = strlen(base);
    if (len == 0 || len >= sizeof(lower)) {
        return 0;
    }
    for (size_t index = 0; index <= len; index++) {
        lower[index] = (char)tolower((unsigned char)base[index]);
    }
    return strstr(lower, "activation") != NULL
        || strstr(lower, "action") != NULL
        || strstr(lower, "quick") != NULL
        || strstr(lower, "scenario") != NULL
        || strstr(lower, "favorite") != NULL
        || strstr(lower, "favourite") != NULL
        || strstr(lower, "prefer") != NULL
        || strstr(lower, "shortcut") != NULL
        || strstr(lower, "openwebnet") != NULL;
}

static uint32_t fnv1a32(const char *value)
{
    uint32_t hash = 2166136261u;

    while (*value != '\0') {
        hash ^= (unsigned char)*value++;
        hash *= 16777619u;
    }
    return hash;
}

static int activation_duplicate(
    const struct c300x_activation_discovery *discovery,
    const struct c300x_activation *activation
)
{
    for (int index = 0; index < discovery->count; index++) {
        const struct c300x_activation *existing = &discovery->items[index];

        if (strcmp(existing->id, activation->id) == 0) {
            return 1;
        }
        if (activation->address[0] != '\0'
            && strcmp(existing->type, activation->type) == 0
            && strcmp(existing->address, activation->address) == 0) {
            return 1;
        }
        if (activation->press_command[0] != '\0'
            && strcmp(existing->press_command, activation->press_command) == 0) {
            return 1;
        }
    }
    return 0;
}

static int activation_conflicts_with_config(
    const struct c300x_config *config,
    const struct c300x_activation *activation
)
{
    for (int index = 0; index < config->activations_count; index++) {
        const struct c300x_activation *existing = &config->activations[index];

        if (strcmp(existing->id, activation->id) == 0) {
            return 1;
        }
        if (activation->address[0] != '\0'
            && strcmp(existing->type, activation->type) == 0
            && strcmp(existing->address, activation->address) == 0) {
            return 1;
        }
        if (activation->press_command[0] != '\0'
            && strcmp(existing->press_command, activation->press_command) == 0) {
            return 1;
        }
    }
    return 0;
}

static void trim_text(char *value)
{
    size_t start = 0;
    size_t end = strlen(value);

    while (value[start] != '\0' && isspace((unsigned char)value[start])) {
        start++;
    }
    while (end > start && isspace((unsigned char)value[end - 1])) {
        end--;
    }
    if (start > 0) {
        memmove(value, value + start, end - start);
    }
    value[end - start] = '\0';
}

static int copy_quoted_value_after(
    const char *start,
    const char *end,
    const char *key,
    char *out,
    size_t out_len
)
{
    const char *found = start;
    const char *last = NULL;
    size_t key_len = strlen(key);

    while (found < end) {
        found = strstr(found, key);
        if (found == NULL || found >= end) {
            break;
        }
        last = found;
        found += key_len;
    }
    if (last == NULL) {
        return 0;
    }
    last += key_len;
    while (last < end && (*last == ' ' || *last == '\t' || *last == ':' || *last == '=')) {
        last++;
    }
    if (last >= end || (*last != '"' && *last != '\'')) {
        return 0;
    }
    {
        char quote = *last++;
        size_t written = 0;

        while (last < end && *last != quote && *last != '\n' && *last != '\r') {
            char ch = *last++;

            if (ch == '\\' && last < end) {
                ch = *last++;
            }
            if (written + 1 < out_len && isprint((unsigned char)ch)) {
                out[written++] = ch;
            }
        }
        if (out_len > 0) {
            out[written] = '\0';
        }
        trim_text(out);
        return out[0] != '\0';
    }
}

static const char *last_key_before(const char *start, const char *end, const char *key)
{
    const char *found = start;
    const char *last = NULL;
    size_t key_len = strlen(key);

    while (found < end) {
        found = strstr(found, key);
        if (found == NULL || found >= end) {
            break;
        }
        last = found;
        found += key_len;
    }
    return last;
}

static void discover_name_near_frame(
    const char *document,
    const char *frame_start,
    const char *fallback,
    char *out,
    size_t out_len
)
{
    const char *start = frame_start - document > C300X_DISCOVERY_CONTEXT_BYTES
        ? frame_start - C300X_DISCOVERY_CONTEXT_BYTES
        : document;
    const char *keys[] = {
        "\"name\"",
        "\"label\"",
        "\"title\"",
        "\"text\"",
        "name=",
        "label=",
        "title=",
        NULL
    };
    const char *closest = NULL;
    const char *closest_key = NULL;

    for (int index = 0; keys[index] != NULL; index++) {
        const char *candidate = last_key_before(start, frame_start, keys[index]);

        if (candidate != NULL && (closest == NULL || candidate > closest)) {
            closest = candidate;
            closest_key = keys[index];
        }
    }
    if (closest != NULL
        && copy_quoted_value_after(closest, frame_start, closest_key, out, out_len)) {
        return;
    }
    safe_copy(out, out_len, fallback);
}

static int extract_address(
    const char *frame,
    const char *prefix,
    char *address,
    size_t address_len
)
{
    const char *start = frame + strlen(prefix);
    const char *end = strstr(start, "##");
    size_t len;

    if (end == NULL || end <= start) {
        return 0;
    }
    len = (size_t)(end - start);
    if (len >= address_len) {
        return 0;
    }
    memcpy(address, start, len);
    address[len] = '\0';
    return address_is_valid(address);
}

static void sanitize_activation_name(char *name)
{
    size_t write_index = 0;

    for (size_t read_index = 0; name[read_index] != '\0'; read_index++) {
        unsigned char ch = (unsigned char)name[read_index];

        if (ch < 32 || ch == 127) {
            continue;
        }
        if (write_index + 1 < C300X_MAX_ACTIVATION_NAME_LEN) {
            name[write_index++] = (char)ch;
        }
    }
    name[write_index] = '\0';
    trim_text(name);
}

static void build_activation_id(
    const struct c300x_activation *activation,
    char *out,
    size_t out_len
)
{
    if (strcmp(activation->type, "lock") == 0
        && activation->address[0] != '\0'
        && strlen(activation->address) <= 20) {
        snprintf(out, out_len, "device_lock_%s", activation->address);
    } else if (strcmp(activation->type, "stair_light") == 0
        && activation->address[0] != '\0'
        && strlen(activation->address) <= 19) {
        snprintf(out, out_len, "device_stair_%s", activation->address);
    } else {
        snprintf(out, out_len, "device_action_%08x", fnv1a32(activation->press_command));
    }
    for (size_t index = 0; out[index] != '\0'; index++) {
        if (!isalnum((unsigned char)out[index]) && out[index] != '_' && out[index] != '-') {
            out[index] = '_';
        }
    }
}

static void add_activation(
    const struct c300x_config *config,
    struct c300x_activation_discovery *discovery,
    const struct c300x_activation *activation
)
{
    if (discovery->count >= C300X_MAX_DISCOVERED_ACTIVATIONS) {
        discovery->truncated = 1;
        return;
    }
    if (activation_conflicts_with_config(config, activation)
        || activation_duplicate(discovery, activation)) {
        return;
    }
    discovery->items[discovery->count++] = *activation;
}

static int frame_end_index(const char *ptr)
{
    for (int index = 0; ptr[index] != '\0' && index < C300X_MAX_FRAME_LEN - 1; index++) {
        if (ptr[index] == '#' && ptr[index + 1] == '#') {
            return index + 2;
        }
    }
    return -1;
}

static void parse_document_for_activations(
    const struct c300x_config *config,
    struct c300x_activation_discovery *discovery,
    const char *document
)
{
    const char *ptr = document;

    while ((ptr = strchr(ptr, '*')) != NULL) {
        struct c300x_activation activation;
        char frame[C300X_MAX_FRAME_LEN];
        char fallback[C300X_MAX_ACTIVATION_NAME_LEN];
        int end_index = frame_end_index(ptr);

        if (end_index <= 0 || end_index >= (int)sizeof(frame)) {
            ptr++;
            continue;
        }
        memcpy(frame, ptr, (size_t)end_index);
        frame[end_index] = '\0';
        ptr += end_index;
        if (!frame_is_valid(frame)) {
            continue;
        }

        memset(&activation, 0, sizeof(activation));
        safe_copy(activation.address_mode, sizeof(activation.address_mode), "manual");
        if (strncmp(frame, "*8*19*", strlen("*8*19*")) == 0) {
            safe_copy(activation.type, sizeof(activation.type), "lock");
            if (!extract_address(frame, "*8*19*", activation.address, sizeof(activation.address))) {
                continue;
            }
            snprintf(
                activation.release_command,
                sizeof(activation.release_command),
                "*8*20*%s##",
                activation.address
            );
            snprintf(fallback, sizeof(fallback), "Door lock %s", activation.address);
        } else if (strncmp(frame, "*8*21*", strlen("*8*21*")) == 0) {
            safe_copy(activation.type, sizeof(activation.type), "stair_light");
            if (!extract_address(frame, "*8*21*", activation.address, sizeof(activation.address))) {
                continue;
            }
            snprintf(fallback, sizeof(fallback), "Stair light %s", activation.address);
        } else {
            continue;
        }
        safe_copy(activation.press_command, sizeof(activation.press_command), frame);
        build_activation_id(&activation, activation.id, sizeof(activation.id));
        discover_name_near_frame(document, ptr - end_index, fallback, activation.name, sizeof(activation.name));
        sanitize_activation_name(activation.name);
        if (activation.name[0] == '\0') {
            safe_copy(activation.name, sizeof(activation.name), fallback);
        }
        add_activation(config, discovery, &activation);
    }
}

static char *read_small_file(const char *path)
{
    FILE *file;
    long size;
    char *buffer;

    file = fopen(path, "rb");
    if (file == NULL) {
        return NULL;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return NULL;
    }
    size = ftell(file);
    if (size < 0 || size > C300X_DISCOVERY_MAX_FILE_BYTES) {
        fclose(file);
        return NULL;
    }
    if (fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return NULL;
    }
    buffer = calloc((size_t)size + 1, 1);
    if (buffer == NULL) {
        fclose(file);
        return NULL;
    }
    if (fread(buffer, 1, (size_t)size, file) != (size_t)size) {
        free(buffer);
        fclose(file);
        return NULL;
    }
    fclose(file);
    return buffer;
}

static void scan_file(
    const struct c300x_config *config,
    struct c300x_activation_discovery *discovery,
    const char *path
)
{
    char *document;

    if (discovery->scanned_files >= C300X_DISCOVERY_MAX_FILES
        || discovery->truncated
        || !discovery_path_allowed(path)
        || !basename_has_activation_hint(path)) {
        return;
    }
    document = read_small_file(path);
    if (document == NULL) {
        return;
    }
    discovery->scanned_files++;
    parse_document_for_activations(config, discovery, document);
    free(document);
}

static void scan_path(
    const struct c300x_config *config,
    struct c300x_activation_discovery *discovery,
    const char *path,
    int depth
)
{
    C300X_DISCOVERY_STAT_STRUCT status;
    DIR *dir;
    struct dirent *entry;

    if (discovery->scanned_files >= C300X_DISCOVERY_MAX_FILES
        || discovery->truncated
        || path == NULL
        || path[0] == '\0'
        || !discovery_path_allowed(path)
        || stat_path(path, &status) != 0) {
        return;
    }
    if (S_ISREG(status.st_mode)) {
        scan_file(config, discovery, path);
        return;
    }
    if (!S_ISDIR(status.st_mode) || depth >= C300X_DISCOVERY_MAX_DEPTH) {
        return;
    }
    dir = opendir(path);
    if (dir == NULL) {
        return;
    }
    while ((entry = readdir(dir)) != NULL) {
        char child[C300X_MAX_PATH_LEN];

        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        if (snprintf(child, sizeof(child), "%s/%s", path, entry->d_name) >= (int)sizeof(child)) {
            continue;
        }
        scan_path(config, discovery, child, depth + 1);
        if (discovery->scanned_files >= C300X_DISCOVERY_MAX_FILES || discovery->truncated) {
            break;
        }
    }
    closedir(dir);
}

void c300x_activation_discovery_reset(struct c300x_activation_discovery *discovery)
{
    memset(discovery, 0, sizeof(*discovery));
}

void c300x_activation_discover(
    const struct c300x_config *config,
    struct c300x_activation_discovery *discovery
)
{
    c300x_activation_discovery_reset(discovery);
    discovery->available = 1;
    if (!config->activations_enabled || !config->activations_auto_discover) {
        return;
    }
    for (int index = 0; index < config->activation_discovery_root_count; index++) {
        scan_path(config, discovery, config->activation_discovery_roots[index], 0);
        if (discovery->scanned_files >= C300X_DISCOVERY_MAX_FILES || discovery->truncated) {
            break;
        }
    }
}
