#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#define _POSIX_C_SOURCE 200809L

#include "device_user.h"
#include "string_util.h"

#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <sys/stat.h>
#include <unistd.h>

#ifndef FLEXISIP_CONFIG_FILE
#define FLEXISIP_CONFIG_FILE "/home/bticino/cfg/flexisip.conf"
#endif
#ifndef FLEXISIP_DOMAIN_FILE
#define FLEXISIP_DOMAIN_FILE "/etc/flexisip/domain-registration.conf"
#endif
#ifndef FLEXISIP_USERS_DIR
#define FLEXISIP_USERS_DIR "/etc/flexisip/users"
#endif
#ifndef FLEXISIP_USERS_FILE
#define FLEXISIP_USERS_FILE "/etc/flexisip/users/users.db.txt"
#endif
#ifndef FLEXISIP_ACCOUNTS_FILE
#define FLEXISIP_ACCOUNTS_FILE "/etc/flexisip/users/accounts.txt"
#endif
#ifndef FLEXISIP_ROUTE_INT_FILE
#define FLEXISIP_ROUTE_INT_FILE "/etc/flexisip/users/route_int.conf"
#endif
#ifndef FLEXISIP_ROUTE_EXT_FILE
#define FLEXISIP_ROUTE_EXT_FILE "/etc/flexisip/users/route_ext.conf"
#endif
#ifndef FLEXISIP_ROUTE_ACTIVE_FILE
#define FLEXISIP_ROUTE_ACTIVE_FILE "/etc/flexisip/users/route.conf"
#endif
#define DEVICE_USER_MAX_FILE_SIZE 8192
#define DEVICE_USER_UUID_LEN 37

#ifdef __arm__
#define C300X_DEVICE_USER_STAT_STRUCT struct stat64
#else
#define C300X_DEVICE_USER_STAT_STRUCT struct stat
#endif

struct file_buffer {
    char *data;
    size_t len;
    mode_t mode;
    int exists;
};

static int device_user_stat_path(
    const char *path,
    C300X_DEVICE_USER_STAT_STRUCT *status
)
{
#ifdef __arm__
    return (int)syscall(SYS_stat64, path, status);
#else
    return stat(path, status);
#endif
}

static int device_user_lstat_path(
    const char *path,
    C300X_DEVICE_USER_STAT_STRUCT *status
)
{
#ifdef __arm__
    return (int)syscall(SYS_lstat64, path, status);
#else
    return lstat(path, status);
#endif
}

static void set_error(char *error, size_t error_len, const char *message)
{
    if (error != NULL && error_len > 0) {
        c300x_copy_string(error, error_len, message != NULL ? message : "device_user_failed");
    }
}

static int sip_string_is_safe(const char *value)
{
    if (value == NULL || value[0] == '\0') {
        return 0;
    }
    for (const char *p = value; *p != '\0'; p++) {
        unsigned char ch = (unsigned char)*p;
        if (
            (ch >= 'a' && ch <= 'z')
            || (ch >= 'A' && ch <= 'Z')
            || (ch >= '0' && ch <= '9')
            || ch == '.'
            || ch == '-'
            || ch == '_'
            || ch == '@'
            || ch == ':'
            || ch == ';'
            || ch == '='
        ) {
            continue;
        }
        return 0;
    }
    return 1;
}

static int copy_checked(char *dest, size_t dest_len, const char *value)
{
    if (dest == NULL || dest_len == 0 || value == NULL || strlen(value) >= dest_len) {
        return 0;
    }
    c300x_copy_string(dest, dest_len, value);
    return 1;
}

static int read_first_line(const char *path, char *out, size_t out_len)
{
    FILE *fp = fopen(path, "r");
    if (fp == NULL) {
        return 0;
    }
    if (fgets(out, (int)out_len, fp) == NULL) {
        fclose(fp);
        return 0;
    }
    fclose(fp);
    for (char *p = out; *p != '\0'; p++) {
        if (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') {
            *p = '\0';
            break;
        }
    }
    return out[0] != '\0' && sip_string_is_safe(out);
}

static int read_flexisip_config_domain(char *out, size_t out_len)
{
    FILE *fp = fopen(FLEXISIP_CONFIG_FILE, "r");
    char line[512];
    char candidate[128] = "";

    if (out == NULL || out_len == 0) {
        return 0;
    }
    out[0] = '\0';
    if (fp == NULL) {
        return 0;
    }
    while (fgets(line, sizeof(line), fp) != NULL) {
        const char *value = NULL;
        if (strncmp(line, "reg-domains=", 12) == 0) {
            value = line + 12;
        } else if (candidate[0] == '\0' && strncmp(line, "auth-domains=", 13) == 0) {
            value = line + 13;
        } else if (candidate[0] == '\0' && strncmp(line, "aliases=", 8) == 0) {
            value = line + 8;
        }
        if (value == NULL) {
            continue;
        }
        size_t len = strcspn(value, " \t\r\n,;");
        if (len == 0 || len >= sizeof(candidate)) {
            continue;
        }
        memcpy(candidate, value, len);
        candidate[len] = '\0';
        if (sip_string_is_safe(candidate) && strncmp(line, "reg-domains=", 12) == 0) {
            break;
        }
    }
    fclose(fp);
    return copy_checked(out, out_len, candidate) && sip_string_is_safe(out);
}

static int split_sip_aor(
    const char *aor,
    char *user,
    size_t user_len,
    char *host,
    size_t host_len
)
{
    const char *body = aor;
    const char *at;
    size_t left_len;
    size_t right_len;

    if (strncasecmp(body, "sip:", 4) == 0) {
        body += 4;
    }
    if (!sip_string_is_safe(body)) {
        return 0;
    }
    at = strchr(body, '@');
    if (at == NULL || at == body || at[1] == '\0') {
        return 0;
    }
    left_len = (size_t)(at - body);
    right_len = strlen(at + 1);
    if (left_len >= user_len || right_len >= host_len) {
        return 0;
    }
    memcpy(user, body, left_len);
    user[left_len] = '\0';
    memcpy(host, at + 1, right_len);
    host[right_len] = '\0';
    return sip_string_is_safe(user) && sip_string_is_safe(host);
}

static int first_token(char *line, char *out, size_t out_len)
{
    char *start = line;
    size_t len = 0;

    while (*start == ' ' || *start == '\t') {
        start++;
    }
    while (
        start[len] != '\0'
        && start[len] != ' '
        && start[len] != '\t'
        && start[len] != '\r'
        && start[len] != '\n'
    ) {
        len++;
    }
    if (len == 0 || len >= out_len) {
        return 0;
    }
    memcpy(out, start, len);
    out[len] = '\0';
    return sip_string_is_safe(out);
}

static int first_users_file_domain(const char *content, char *host, size_t host_len)
{
    const char *cursor = content != NULL ? content : "";

    if (host == NULL || host_len == 0) {
        return 0;
    }
    host[0] = '\0';
    while (*cursor != '\0') {
        char line[512];
        char token[256];
        char user[128];
        const char *line_end = strchr(cursor, '\n');
        size_t line_len = line_end != NULL ? (size_t)(line_end - cursor) : strlen(cursor);

        if (line_len >= sizeof(line)) {
            line_len = sizeof(line) - 1;
        }
        memcpy(line, cursor, line_len);
        line[line_len] = '\0';
        if (
            first_token(line, token, sizeof(token))
            && strchr(token, '@') != NULL
            && split_sip_aor(token, user, sizeof(user), host, host_len)
        ) {
            return 1;
        }
        if (line_end == NULL) {
            break;
        }
        cursor = line_end + 1;
    }
    return 0;
}

static int user_is_homeassistant(const char *user)
{
    size_t prefix_len = strlen(C300X_DEVICE_USER_ACCOUNT);

    return strcmp(user, C300X_DEVICE_USER_ACCOUNT) == 0
        || (
            strncmp(user, C300X_DEVICE_USER_ACCOUNT, prefix_len) == 0
            && user[prefix_len] == '-'
        );
}

static int read_file_buffer(
    const char *path,
    struct file_buffer *buffer,
    char *error,
    size_t error_len
)
{
    FILE *fp;
    C300X_DEVICE_USER_STAT_STRUCT st;
    size_t read_len;

    memset(buffer, 0, sizeof(*buffer));
    buffer->mode = 0644;
    if (device_user_stat_path(path, &st) != 0) {
        if (errno == ENOENT) {
            return 1;
        }
        set_error(error, error_len, "stat_failed");
        return 0;
    }
    if (!S_ISREG(st.st_mode)) {
        set_error(error, error_len, "not_regular_file");
        return 0;
    }
    if (st.st_size < 0 || st.st_size > DEVICE_USER_MAX_FILE_SIZE) {
        set_error(error, error_len, "file_too_large");
        return 0;
    }
    buffer->data = calloc((size_t)st.st_size + 2, 1);
    if (buffer->data == NULL) {
        set_error(error, error_len, "out_of_memory");
        return 0;
    }
    fp = fopen(path, "r");
    if (fp == NULL) {
        free(buffer->data);
        buffer->data = NULL;
        set_error(error, error_len, "open_failed");
        return 0;
    }
    read_len = fread(buffer->data, 1, (size_t)st.st_size, fp);
    if (ferror(fp)) {
        fclose(fp);
        free(buffer->data);
        buffer->data = NULL;
        set_error(error, error_len, "read_failed");
        return 0;
    }
    fclose(fp);
    buffer->data[read_len] = '\0';
    buffer->len = read_len;
    buffer->mode = st.st_mode & 0777;
    buffer->exists = 1;
    return 1;
}

static void free_file_buffer(struct file_buffer *buffer)
{
    if (buffer != NULL) {
        free(buffer->data);
        buffer->data = NULL;
        buffer->len = 0;
    }
}

static int write_file_atomic(
    const char *path,
    const char *data,
    size_t len,
    mode_t mode,
    char *error,
    size_t error_len
)
{
    char tmp_path[C300X_MAX_PATH_LEN];
    FILE *fp;
    int fd;

    if (snprintf(tmp_path, sizeof(tmp_path), "%s.c300x-ha.tmp", path) >= (int)sizeof(tmp_path)) {
        set_error(error, error_len, "tmp_path_too_long");
        return 0;
    }
    fp = fopen(tmp_path, "w");
    if (fp == NULL) {
        set_error(error, error_len, "tmp_open_failed");
        return 0;
    }
    if (len > 0 && fwrite(data, 1, len, fp) != len) {
        fclose(fp);
        unlink(tmp_path);
        set_error(error, error_len, "tmp_write_failed");
        return 0;
    }
    fd = fileno(fp);
    if (fd < 0 || fchmod(fd, mode) != 0) {
        fclose(fp);
        unlink(tmp_path);
        set_error(error, error_len, "chmod_failed");
        return 0;
    }
    (void)fsync(fd);
    if (fclose(fp) != 0) {
        unlink(tmp_path);
        set_error(error, error_len, "tmp_close_failed");
        return 0;
    }
    if (rename(tmp_path, path) != 0) {
        unlink(tmp_path);
        set_error(error, error_len, "rename_failed");
        return 0;
    }
    return 1;
}

static int ensure_users_dir(char *error, size_t error_len)
{
    C300X_DEVICE_USER_STAT_STRUCT st;

    if (device_user_stat_path(FLEXISIP_USERS_DIR, &st) == 0) {
        if (S_ISDIR(st.st_mode)) {
            return 1;
        }
        set_error(error, error_len, "users_dir_not_directory");
        return 0;
    }
    if (errno != ENOENT) {
        set_error(error, error_len, "users_dir_stat_failed");
        return 0;
    }
    if (mkdir(FLEXISIP_USERS_DIR, 0755) != 0 && errno != EEXIST) {
        set_error(error, error_len, "users_dir_create_failed");
        return 0;
    }
    return 1;
}

static int init_missing_file_buffer(
    struct file_buffer *buffer,
    const char *content,
    int *changed,
    char *error,
    size_t error_len
)
{
    size_t len;

    if (buffer->exists) {
        return 1;
    }
    if (content == NULL) {
        content = "";
    }
    len = strlen(content);
    buffer->data = calloc(len + 1, 1);
    if (buffer->data == NULL) {
        set_error(error, error_len, "out_of_memory");
        return 0;
    }
    memcpy(buffer->data, content, len);
    buffer->len = len;
    buffer->mode = 0644;
    buffer->exists = 1;
    *changed = 1;
    return 1;
}

static int ensure_active_route_link(
    const struct file_buffer *route_conf,
    char *error,
    size_t error_len
)
{
    C300X_DEVICE_USER_STAT_STRUCT st;

    if (route_conf->exists || device_user_lstat_path(FLEXISIP_ROUTE_ACTIVE_FILE, &st) == 0) {
        return 1;
    }
    if (errno != ENOENT) {
        set_error(error, error_len, "route_conf_lstat_failed");
        return 0;
    }
    if (symlink(FLEXISIP_ROUTE_INT_FILE, FLEXISIP_ROUTE_ACTIVE_FILE) != 0 && errno != EEXIST) {
        set_error(error, error_len, "route_conf_link_failed");
        return 0;
    }
    return 1;
}

static int secure_random(unsigned char *out, size_t len)
{
    FILE *fp = fopen("/dev/urandom", "rb");
    size_t done;

    if (fp == NULL) {
        return 0;
    }
    done = fread(out, 1, len, fp);
    fclose(fp);
    return done == len;
}

static int format_uuid(const unsigned char *bytes, char *out, size_t out_len)
{
    if (out_len < DEVICE_USER_UUID_LEN) {
        return 0;
    }
    return snprintf(
        out,
        out_len,
        "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        bytes[0],
        bytes[1],
        bytes[2],
        bytes[3],
        bytes[4],
        bytes[5],
        bytes[6],
        bytes[7],
        bytes[8],
        bytes[9],
        bytes[10],
        bytes[11],
        bytes[12],
        bytes[13],
        bytes[14],
        bytes[15]
    ) == DEVICE_USER_UUID_LEN - 1;
}

static int random_uuid(char *out, size_t out_len)
{
    unsigned char bytes[16];

    if (!secure_random(bytes, sizeof(bytes))) {
        return 0;
    }
    bytes[6] = (unsigned char)((bytes[6] & 0x0f) | 0x40);
    bytes[8] = (unsigned char)((bytes[8] & 0x3f) | 0x80);
    return format_uuid(bytes, out, out_len);
}

static int random_hex(char *out, size_t out_len)
{
    unsigned char bytes[16];
    static const char hex[] = "0123456789abcdef";

    if (out_len < 33 || !secure_random(bytes, sizeof(bytes))) {
        return 0;
    }
    for (size_t i = 0; i < sizeof(bytes); i++) {
        out[i * 2] = hex[(bytes[i] >> 4) & 0x0f];
        out[(i * 2) + 1] = hex[bytes[i] & 0x0f];
    }
    out[32] = '\0';
    return 1;
}

static int parse_users_file(
    const char *content,
    char *device_domain,
    size_t device_domain_len,
    char *ha_aor,
    size_t ha_aor_len,
    int *ha_present
)
{
    const char *cursor = content != NULL ? content : "";

    if (device_domain != NULL && device_domain_len > 0) {
        device_domain[0] = '\0';
    }
    if (ha_aor != NULL && ha_aor_len > 0) {
        ha_aor[0] = '\0';
    }
    if (ha_present != NULL) {
        *ha_present = 0;
    }
    while (*cursor != '\0') {
        char line[512];
        char token[256];
        char user[128];
        char host[128];
        const char *line_end = strchr(cursor, '\n');
        size_t line_len = line_end != NULL ? (size_t)(line_end - cursor) : strlen(cursor);

        if (line_len >= sizeof(line)) {
            line_len = sizeof(line) - 1;
        }
        memcpy(line, cursor, line_len);
        line[line_len] = '\0';
        if (first_token(line, token, sizeof(token)) && strchr(token, '@') != NULL) {
            if (split_sip_aor(token, user, sizeof(user), host, sizeof(host))) {
                if (strcmp(user, "c300x") == 0) {
                    if (device_domain != NULL && device_domain[0] == '\0') {
                        (void)copy_checked(device_domain, device_domain_len, host);
                    }
                } else if (user_is_homeassistant(user)) {
                    if (ha_present != NULL) {
                        *ha_present = 1;
                    }
                    if (ha_aor != NULL && ha_aor[0] == '\0') {
                        (void)copy_checked(ha_aor, ha_aor_len, token);
                    }
                }
            }
        }
        if (line_end == NULL) {
            break;
        }
        cursor = line_end + 1;
    }
    return 1;
}

static int accounts_has_homeassistant(const char *content)
{
    const char *needle = "|" C300X_DEVICE_USER_ACCOUNT;
    const char *match = content != NULL ? strstr(content, needle) : NULL;

    while (match != NULL) {
        char next = match[strlen(needle)];
        if (next == '\0' || next == '\r' || next == '\n') {
            return 1;
        }
        match = strstr(match + 1, needle);
    }
    return 0;
}

static int homeassistant_account_label(
    const char *content,
    char *label,
    size_t label_len
)
{
    const char *cursor = content != NULL ? content : "";

    if (label != NULL && label_len > 0) {
        label[0] = '\0';
    }
    while (*cursor != '\0') {
        const char *line_end = strchr(cursor, '\n');
        const char *sep;
        size_t line_len = line_end != NULL ? (size_t)(line_end - cursor) : strlen(cursor);
        size_t name_len;
        size_t account_len;

        sep = memchr(cursor, '|', line_len);
        if (sep != NULL) {
            const char *account = sep + 1;
            while (line_len > 0 && (cursor[line_len - 1] == '\r' || cursor[line_len - 1] == '\n')) {
                line_len--;
            }
            account_len = (size_t)(cursor + line_len - account);
            if (
                account_len == strlen(C300X_DEVICE_USER_ACCOUNT)
                && strncmp(account, C300X_DEVICE_USER_ACCOUNT, account_len) == 0
            ) {
                if (label == NULL || label_len == 0) {
                    return 1;
                }
                name_len = (size_t)(sep - cursor);
                while (name_len > 0 && (cursor[name_len - 1] == ' ' || cursor[name_len - 1] == '\t')) {
                    name_len--;
                }
                if (name_len >= label_len) {
                    name_len = label_len - 1;
                }
                memcpy(label, cursor, name_len);
                label[name_len] = '\0';
                return 1;
            }
        }
        if (line_end == NULL) {
            break;
        }
        cursor = line_end + 1;
    }
    return 0;
}

static void sanitize_account_label(
    const char *input,
    char *out,
    size_t out_len
)
{
    size_t written = 0;
    int previous_space = 1;

    if (out == NULL || out_len == 0) {
        return;
    }
    out[0] = '\0';
    for (const unsigned char *p = (const unsigned char *)(input != NULL ? input : ""); *p != '\0' && written + 1 < out_len; p++) {
        unsigned char ch = *p;
        int is_space = ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n';

        if (is_space) {
            if (!previous_space && written + 1 < out_len) {
                out[written++] = ' ';
                previous_space = 1;
            }
            continue;
        }
        if (ch < 32 || ch > 126 || ch == '|' || ch == '"' || ch == '\\') {
            continue;
        }
        out[written++] = (char)ch;
        previous_space = 0;
    }
    while (written > 0 && out[written - 1] == ' ') {
        written--;
    }
    out[written] = '\0';
    if (out[0] == '\0') {
        snprintf(out, out_len, "%s", C300X_DEVICE_USER_LABEL);
    }
}

static int route_has_homeassistant(const char *content)
{
    return content != NULL
        && (
            strstr(content, "<sip:" C300X_DEVICE_USER_ACCOUNT "@") != NULL
            || strstr(content, "<sip:" C300X_DEVICE_USER_ACCOUNT "-") != NULL
        );
}

static int append_line(
    char **content,
    size_t *len,
    const char *line,
    char *error,
    size_t error_len
)
{
    size_t line_len = strlen(line);
    size_t extra_newline = (*len > 0 && (*content)[*len - 1] != '\n') ? 1 : 0;
    char *updated = realloc(*content, *len + extra_newline + line_len + 1);

    if (updated == NULL) {
        set_error(error, error_len, "out_of_memory");
        return 0;
    }
    *content = updated;
    if (extra_newline) {
        (*content)[*len] = '\n';
        *len += 1;
    }
    memcpy(*content + *len, line, line_len);
    *len += line_len;
    (*content)[*len] = '\0';
    return 1;
}

static int ensure_account_line(
    struct file_buffer *accounts,
    const char *account_label,
    int *changed,
    char *error,
    size_t error_len
)
{
    char safe_label[C300X_DEVICE_USER_LABEL_LEN];
    char existing_label[C300X_DEVICE_USER_LABEL_LEN];
    char *output;
    size_t output_len = 0;
    size_t output_cap;
    const char *cursor;
    int found = 0;
    char expected_line[C300X_DEVICE_USER_LABEL_LEN + sizeof(C300X_DEVICE_USER_ACCOUNT) + 4];

    sanitize_account_label(account_label, safe_label, sizeof(safe_label));
    if (
        homeassistant_account_label(accounts->data, existing_label, sizeof(existing_label))
        && strcmp(existing_label, safe_label) == 0
    ) {
        return 1;
    }
    if (accounts->data == NULL) {
        accounts->data = calloc(1, 1);
        if (accounts->data == NULL) {
            set_error(error, error_len, "out_of_memory");
            return 0;
        }
        accounts->len = 0;
        accounts->mode = 0644;
    }
    if (
        snprintf(
            expected_line,
            sizeof(expected_line),
            "%s|" C300X_DEVICE_USER_ACCOUNT "\n",
            safe_label
        ) >= (int)sizeof(expected_line)
    ) {
        set_error(error, error_len, "account_label_too_long");
        return 0;
    }
    output_cap = accounts->len + strlen(expected_line) + 1;
    output = calloc(output_cap, 1);
    if (output == NULL) {
        set_error(error, error_len, "out_of_memory");
        return 0;
    }
    cursor = accounts->data;
    while (*cursor != '\0') {
        const char *line_end = strchr(cursor, '\n');
        size_t line_len = line_end != NULL ? (size_t)(line_end - cursor) + 1 : strlen(cursor);
        const char *sep = memchr(cursor, '|', line_len);
        int is_homeassistant = 0;

        if (sep != NULL) {
            size_t effective_len = line_len;
            const char *account = sep + 1;
            size_t account_len;

            while (effective_len > 0 && (cursor[effective_len - 1] == '\r' || cursor[effective_len - 1] == '\n')) {
                effective_len--;
            }
            account_len = (size_t)(cursor + effective_len - account);
            is_homeassistant = account_len == strlen(C300X_DEVICE_USER_ACCOUNT)
                && strncmp(account, C300X_DEVICE_USER_ACCOUNT, account_len) == 0;
        }
        if (is_homeassistant) {
            if (!found) {
                if (output_len + strlen(expected_line) >= output_cap) {
                    free(output);
                    set_error(error, error_len, "accounts_too_large");
                    return 0;
                }
                memcpy(output + output_len, expected_line, strlen(expected_line));
                output_len += strlen(expected_line);
                found = 1;
            }
        } else {
            if (output_len + line_len >= output_cap) {
                free(output);
                set_error(error, error_len, "accounts_too_large");
                return 0;
            }
            memcpy(output + output_len, cursor, line_len);
            output_len += line_len;
        }
        if (line_end == NULL) {
            break;
        }
        cursor = line_end + 1;
    }
    if (!found) {
        if (output_len > 0 && output[output_len - 1] != '\n') {
            if (output_len + 1 >= output_cap) {
                free(output);
                set_error(error, error_len, "accounts_too_large");
                return 0;
            }
            output[output_len++] = '\n';
        }
        if (output_len + strlen(expected_line) >= output_cap) {
            free(output);
            set_error(error, error_len, "accounts_too_large");
            return 0;
        }
        memcpy(output + output_len, expected_line, strlen(expected_line));
        output_len += strlen(expected_line);
    }
    output[output_len] = '\0';
    free(accounts->data);
    accounts->data = output;
    accounts->len = output_len;
    *changed = 1;
    return 1;
}

static int ensure_route_target(
    struct file_buffer *route,
    const char *domain,
    const char *ha_aor,
    int *changed,
    char *error,
    size_t error_len
)
{
    char *output;
    size_t output_len = 0;
    size_t output_cap;
    const char *cursor;
    int updated_alluser = 0;
    char new_line[512];

    if (route_has_homeassistant(route->data)) {
        return 1;
    }
    if (route->data == NULL) {
        route->data = calloc(1, 1);
        if (route->data == NULL) {
            set_error(error, error_len, "out_of_memory");
            return 0;
        }
        route->len = 0;
        route->mode = 0644;
    }
    output_cap = route->len + strlen(ha_aor) + strlen(domain) + 128;
    output = calloc(output_cap, 1);
    if (output == NULL) {
        set_error(error, error_len, "out_of_memory");
        return 0;
    }
    cursor = route->data;
    while (*cursor != '\0') {
        const char *line_end = strchr(cursor, '\n');
        size_t line_len = line_end != NULL ? (size_t)(line_end - cursor) + 1 : strlen(cursor);
        int is_alluser = 0;
        size_t copy_len = line_len;

        if (line_len > 0 && line_len < sizeof(new_line)) {
            memcpy(new_line, cursor, line_len);
            new_line[line_len] = '\0';
            is_alluser = strstr(new_line, "<sip:alluser@") != NULL;
        }
        if (is_alluser && !updated_alluser) {
            size_t body_len = line_len;
            size_t remaining;
            int written;
            while (body_len > 0 && (cursor[body_len - 1] == '\n' || cursor[body_len - 1] == '\r')) {
                body_len--;
            }
            if (output_len + body_len + strlen(ha_aor) + 12 >= output_cap) {
                free(output);
                set_error(error, error_len, "route_too_large");
                return 0;
            }
            memcpy(output + output_len, cursor, body_len);
            output_len += body_len;
            remaining = output_cap - output_len;
            written = snprintf(output + output_len, remaining, ", <sip:%s>\n", ha_aor);
            if (written < 0 || (size_t)written >= remaining) {
                free(output);
                set_error(error, error_len, "route_too_large");
                return 0;
            }
            output_len += (size_t)written;
            updated_alluser = 1;
        } else {
            if (output_len + copy_len >= output_cap) {
                free(output);
                set_error(error, error_len, "route_too_large");
                return 0;
            }
            memcpy(output + output_len, cursor, copy_len);
            output_len += copy_len;
        }
        if (line_end == NULL) {
            break;
        }
        cursor = line_end + 1;
    }
    if (!updated_alluser) {
        if (
            snprintf(new_line, sizeof(new_line), "<sip:alluser@%s> <sip:%s>\n", domain, ha_aor)
            >= (int)sizeof(new_line)
        ) {
            free(output);
            set_error(error, error_len, "route_line_too_long");
            return 0;
        }
        if (output_len > 0 && output[output_len - 1] != '\n') {
            if (output_len + 1 >= output_cap) {
                free(output);
                set_error(error, error_len, "route_too_large");
                return 0;
            }
            output[output_len++] = '\n';
        }
        if (output_len + strlen(new_line) >= output_cap) {
            free(output);
            set_error(error, error_len, "route_too_large");
            return 0;
        }
        memcpy(output + output_len, new_line, strlen(new_line));
        output_len += strlen(new_line);
    }
    output[output_len] = '\0';
    free(route->data);
    route->data = output;
    route->len = output_len;
    *changed = 1;
    return 1;
}

static int remove_route_target(
    struct file_buffer *route,
    int *changed,
    char *error,
    size_t error_len
)
{
    char *output;
    size_t output_len = 0;
    const char *cursor;

    if (route->data == NULL || !route_has_homeassistant(route->data)) {
        return 1;
    }
    output = calloc(route->len + 1, 1);
    if (output == NULL) {
        set_error(error, error_len, "out_of_memory");
        return 0;
    }
    cursor = route->data;
    while (*cursor != '\0') {
        const char *line_end = strchr(cursor, '\n');
        size_t line_len = line_end != NULL ? (size_t)(line_end - cursor) + 1 : strlen(cursor);
        char line[1024];
        size_t body_len = line_len;
        char *match;
        int line_had_homeassistant = 0;
        int sip_targets = 0;

        while (body_len > 0 && (cursor[body_len - 1] == '\n' || cursor[body_len - 1] == '\r')) {
            body_len--;
        }
        if (body_len >= sizeof(line)) {
            free(output);
            set_error(error, error_len, "route_line_too_long");
            return 0;
        }
        memcpy(line, cursor, body_len);
        line[body_len] = '\0';
        match = line;
        while ((match = strstr(match, "<sip:")) != NULL) {
            char *token_end = strchr(match, '>');
            char aor[256];
            char user[128];
            char host[128];
            size_t aor_len;
            if (token_end == NULL) {
                break;
            }
            aor_len = (size_t)(token_end - (match + 5));
            if (aor_len >= sizeof(aor)) {
                match = token_end + 1;
                continue;
            }
            memcpy(aor, match + 5, aor_len);
            aor[aor_len] = '\0';
            if (!split_sip_aor(aor, user, sizeof(user), host, sizeof(host)) || !user_is_homeassistant(user)) {
                match = token_end + 1;
                continue;
            }
            line_had_homeassistant = 1;
            char *remove_start = match;
            char *remove_end = token_end + 1;
            char *scan = match;
            while (scan > line && (scan[-1] == ' ' || scan[-1] == '\t')) {
                scan--;
            }
            if (scan > line && scan[-1] == ',') {
                remove_start = scan - 1;
                while (remove_start > line && (remove_start[-1] == ' ' || remove_start[-1] == '\t')) {
                    remove_start--;
                }
            } else {
                scan = remove_end;
                while (*scan == ' ' || *scan == '\t') {
                    scan++;
                }
                if (*scan == ',') {
                    scan++;
                    while (*scan == ' ' || *scan == '\t') {
                        scan++;
                    }
                    remove_end = scan;
                }
            }
            memmove(remove_start, remove_end, strlen(remove_end) + 1);
            match = line;
        }
        for (char *scan = line; (scan = strstr(scan, "<sip:")) != NULL; scan += 5) {
            sip_targets++;
        }
        if (sip_targets > 1 || !line_had_homeassistant) {
            size_t updated_len = strlen(line);
            while (updated_len > 0 && (line[updated_len - 1] == ' ' || line[updated_len - 1] == '\t')) {
                updated_len--;
            }
            if (output_len + updated_len + 1 > route->len) {
                free(output);
                set_error(error, error_len, "route_too_large");
                return 0;
            }
            memcpy(output + output_len, line, updated_len);
            output_len += updated_len;
            if (line_end != NULL) {
                output[output_len++] = '\n';
            }
        }
        if (line_end == NULL) {
            break;
        }
        cursor = line_end + 1;
    }
    output[output_len] = '\0';
    free(route->data);
    route->data = output;
    route->len = output_len;
    *changed = 1;
    return 1;
}

static int read_status_from_buffers(
    const struct file_buffer *users,
    const struct file_buffer *accounts,
    const struct file_buffer *route_int,
    const struct file_buffer *route_ext,
    const struct file_buffer *route_conf,
    int route_conf_symlink,
    struct c300x_device_user_status *status
)
{
    char device_domain[128];
    char ha_aor[256];

    memset(status, 0, sizeof(*status));
    status->status_available = 1;
    status->supported = 1;
    status->route_conf_is_symlink = route_conf_symlink;
    status->writable_files_present = users->exists && route_int->exists && route_ext->exists;
    parse_users_file(
        users->data,
        device_domain,
        sizeof(device_domain),
        ha_aor,
        sizeof(ha_aor),
        &status->homeassistant_user_present
    );
    status->domain_present = device_domain[0] != '\0'
        || first_users_file_domain(users->data, device_domain, sizeof(device_domain))
        || read_first_line(FLEXISIP_DOMAIN_FILE, device_domain, sizeof(device_domain))
        || read_flexisip_config_domain(device_domain, sizeof(device_domain));
    status->accounts_homeassistant_present = accounts_has_homeassistant(accounts->data);
    (void)homeassistant_account_label(
        accounts->data,
        status->account_label,
        sizeof(status->account_label)
    );
    status->route_int_homeassistant_present = route_has_homeassistant(route_int->data);
    status->route_ext_homeassistant_present = route_has_homeassistant(route_ext->data);
    status->route_conf_homeassistant_present = route_has_homeassistant(route_conf->data);
    status->media_identity_available = status->domain_present
        && status->homeassistant_user_present;
    status->routes_consistent = status->homeassistant_user_present
        ? (
            status->accounts_homeassistant_present
            && status->route_int_homeassistant_present
            && !status->route_ext_homeassistant_present
        )
        : 1;
    return 1;
}

int c300x_device_user_read_status(struct c300x_device_user_status *status)
{
    struct file_buffer users;
    struct file_buffer accounts;
    struct file_buffer route_int;
    struct file_buffer route_ext;
    struct file_buffer route_conf;
    C300X_DEVICE_USER_STAT_STRUCT lst;
    int ok = 0;
    char error[C300X_DEVICE_USER_ERROR_LEN] = "";

    if (status == NULL) {
        return 0;
    }
    memset(&users, 0, sizeof(users));
    memset(&accounts, 0, sizeof(accounts));
    memset(&route_int, 0, sizeof(route_int));
    memset(&route_ext, 0, sizeof(route_ext));
    memset(&route_conf, 0, sizeof(route_conf));
    memset(status, 0, sizeof(*status));
    if (
        read_file_buffer(FLEXISIP_USERS_FILE, &users, error, sizeof(error))
        && read_file_buffer(FLEXISIP_ACCOUNTS_FILE, &accounts, error, sizeof(error))
        && read_file_buffer(FLEXISIP_ROUTE_INT_FILE, &route_int, error, sizeof(error))
        && read_file_buffer(FLEXISIP_ROUTE_EXT_FILE, &route_ext, error, sizeof(error))
        && read_file_buffer(FLEXISIP_ROUTE_ACTIVE_FILE, &route_conf, error, sizeof(error))
    ) {
        ok = read_status_from_buffers(
            &users,
            &accounts,
            &route_int,
            &route_ext,
            &route_conf,
            device_user_lstat_path(FLEXISIP_ROUTE_ACTIVE_FILE, &lst) == 0
                && S_ISLNK(lst.st_mode),
            status
        );
    }
    if (!ok) {
        memset(status, 0, sizeof(*status));
        status->supported = 1;
        status->status_available = 0;
        snprintf(status->error, sizeof(status->error), "%s", error[0] != '\0' ? error : "status_failed");
    }
    free_file_buffer(&users);
    free_file_buffer(&accounts);
    free_file_buffer(&route_int);
    free_file_buffer(&route_ext);
    free_file_buffer(&route_conf);
    return ok;
}

int c300x_device_user_media_identity(
    const char *domain_hint,
    struct c300x_device_user_identity *identity
)
{
    struct file_buffer users;
    char device_domain[128];
    char ha_aor[256];
    char host[128];
    char error[C300X_DEVICE_USER_ERROR_LEN] = "";
    int ok = 0;

    if (identity == NULL) {
        return 0;
    }
    memset(identity, 0, sizeof(*identity));
    memset(&users, 0, sizeof(users));
    device_domain[0] = '\0';
    ha_aor[0] = '\0';
    if (!read_file_buffer(FLEXISIP_USERS_FILE, &users, error, sizeof(error))) {
        return 0;
    }
    for (const char *cursor = users.data != NULL ? users.data : ""; *cursor != '\0';) {
        char line[512];
        char token[256];
        char user[128];
        char token_host[128];
        const char *line_end = strchr(cursor, '\n');
        size_t line_len = line_end != NULL ? (size_t)(line_end - cursor) : strlen(cursor);

        if (line_len >= sizeof(line)) {
            line_len = sizeof(line) - 1;
        }
        memcpy(line, cursor, line_len);
        line[line_len] = '\0';
        if (
            first_token(line, token, sizeof(token))
            && strchr(token, '@') != NULL
            && split_sip_aor(token, user, sizeof(user), token_host, sizeof(token_host))
        ) {
            if (strcmp(user, "c300x") == 0 && device_domain[0] == '\0') {
                (void)copy_checked(device_domain, sizeof(device_domain), token_host);
            } else if (user_is_homeassistant(user) && ha_aor[0] == '\0') {
                (void)copy_checked(ha_aor, sizeof(ha_aor), token);
            }
        }
        if (line_end == NULL) {
            break;
        }
        cursor = line_end + 1;
    }
    if (
        ha_aor[0] != '\0'
        && split_sip_aor(ha_aor, identity->from_user, sizeof(identity->from_user), host, sizeof(host))
    ) {
        if (device_domain[0] != '\0') {
            ok = copy_checked(identity->domain, sizeof(identity->domain), device_domain);
        } else if (domain_hint != NULL && domain_hint[0] != '\0') {
            ok = copy_checked(identity->domain, sizeof(identity->domain), domain_hint);
        } else {
            ok = copy_checked(identity->domain, sizeof(identity->domain), host);
        }
        if (ok && sip_string_is_safe(identity->domain)) {
            ok = snprintf(identity->from_aor, sizeof(identity->from_aor), "%s@%s", identity->from_user, identity->domain) < (int)sizeof(identity->from_aor)
                && snprintf(identity->to_aor, sizeof(identity->to_aor), "c300x@%s", identity->domain) < (int)sizeof(identity->to_aor);
        }
    }
    free_file_buffer(&users);
    return ok;
}

int c300x_device_user_ensure_homeassistant(
    struct c300x_device_user_status *status,
    const char *account_label,
    char *error,
    size_t error_len
)
{
    struct file_buffer users;
    struct file_buffer accounts;
    struct file_buffer route_int;
    struct file_buffer route_ext;
    struct file_buffer route_conf;
    char device_domain[128];
    char ha_aor[256];
    char uuid[DEVICE_USER_UUID_LEN];
    char digest[33];
    char user_line[512];
    int ha_present = 0;
    int users_changed = 0;
    int accounts_changed = 0;
    int route_int_changed = 0;
    int route_ext_changed = 0;
    int ok = 0;

    memset(&users, 0, sizeof(users));
    memset(&accounts, 0, sizeof(accounts));
    memset(&route_int, 0, sizeof(route_int));
    memset(&route_ext, 0, sizeof(route_ext));
    memset(&route_conf, 0, sizeof(route_conf));
    if (
        !read_file_buffer(FLEXISIP_USERS_FILE, &users, error, error_len)
        || !read_file_buffer(FLEXISIP_ACCOUNTS_FILE, &accounts, error, error_len)
        || !read_file_buffer(FLEXISIP_ROUTE_INT_FILE, &route_int, error, error_len)
        || !read_file_buffer(FLEXISIP_ROUTE_EXT_FILE, &route_ext, error, error_len)
        || !read_file_buffer(FLEXISIP_ROUTE_ACTIVE_FILE, &route_conf, error, error_len)
    ) {
        goto cleanup;
    }
    if (
        !ensure_users_dir(error, error_len)
        || !init_missing_file_buffer(&users, "version:1\n", &users_changed, error, error_len)
        || !init_missing_file_buffer(&accounts, "", &accounts_changed, error, error_len)
        || !init_missing_file_buffer(&route_int, "", &route_int_changed, error, error_len)
        || !init_missing_file_buffer(&route_ext, "", &route_ext_changed, error, error_len)
        || !ensure_active_route_link(&route_conf, error, error_len)
    ) {
        goto cleanup;
    }
    parse_users_file(
        users.data,
        device_domain,
        sizeof(device_domain),
        ha_aor,
        sizeof(ha_aor),
        &ha_present
    );
    if (device_domain[0] == '\0') {
        if (
            !first_users_file_domain(users.data, device_domain, sizeof(device_domain))
            && !read_first_line(FLEXISIP_DOMAIN_FILE, device_domain, sizeof(device_domain))
            && !read_flexisip_config_domain(device_domain, sizeof(device_domain))
        ) {
            set_error(error, error_len, "device_domain_missing");
            goto cleanup;
        }
    }
    if (!ha_present) {
        if (!random_uuid(uuid, sizeof(uuid)) || !random_hex(digest, sizeof(digest))) {
            set_error(error, error_len, "secure_random_failed");
            goto cleanup;
        }
        if (
            snprintf(
                ha_aor,
                sizeof(ha_aor),
                C300X_DEVICE_USER_ACCOUNT "-%s@%s",
                uuid,
                device_domain
            ) >= (int)sizeof(ha_aor)
            || snprintf(user_line, sizeof(user_line), "%s md5:%s ;\n", ha_aor, digest) >= (int)sizeof(user_line)
        ) {
            set_error(error, error_len, "homeassistant_user_too_long");
            goto cleanup;
        }
        if (!append_line(&users.data, &users.len, user_line, error, error_len)) {
            goto cleanup;
        }
        users_changed = 1;
    }
    if (
        !ensure_account_line(&accounts, account_label, &accounts_changed, error, error_len)
        || !ensure_route_target(&route_int, device_domain, ha_aor, &route_int_changed, error, error_len)
        || !remove_route_target(&route_ext, &route_ext_changed, error, error_len)
    ) {
        goto cleanup;
    }
    if (users_changed && !write_file_atomic(FLEXISIP_USERS_FILE, users.data, users.len, users.mode, error, error_len)) {
        goto cleanup;
    }
    if (accounts_changed && !write_file_atomic(FLEXISIP_ACCOUNTS_FILE, accounts.data, accounts.len, accounts.mode, error, error_len)) {
        goto cleanup;
    }
    if (route_int_changed && !write_file_atomic(FLEXISIP_ROUTE_INT_FILE, route_int.data, route_int.len, route_int.mode, error, error_len)) {
        goto cleanup;
    }
    if (route_ext_changed && !write_file_atomic(FLEXISIP_ROUTE_EXT_FILE, route_ext.data, route_ext.len, route_ext.mode, error, error_len)) {
        goto cleanup;
    }
    ok = 1;
    if (status != NULL) {
        (void)c300x_device_user_read_status(status);
    }

cleanup:
    free_file_buffer(&users);
    free_file_buffer(&accounts);
    free_file_buffer(&route_int);
    free_file_buffer(&route_ext);
    free_file_buffer(&route_conf);
    return ok;
}
