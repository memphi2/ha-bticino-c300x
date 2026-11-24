#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#include "memo_store.h"
#include "string_util.h"

#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <strings.h>
#include <string.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <sys/stat.h>
#include <unistd.h>

#ifdef __arm__
#define C300X_MEMO_STAT_STRUCT struct stat64
#else
#define C300X_MEMO_STAT_STRUCT struct stat
#endif

static int memo_stat_path(const char *path, C300X_MEMO_STAT_STRUCT *status)
{
#ifdef __arm__
    return (int)syscall(SYS_stat64, path, status);
#else
    return stat(path, status);
#endif
}

static void set_error(char *error, size_t error_len, const char *value)
{
    if (error_len == 0) {
        return;
    }
    c300x_copy_string(error, error_len, value);
}

static const char *trim_ascii(char *value)
{
    char *start = value;
    char *end;
    while (*start != '\0' && isspace((unsigned char)*start)) {
        start++;
    }
    end = start + strlen(start);
    while (end > start && isspace((unsigned char)end[-1])) {
        end--;
    }
    *end = '\0';
    return start;
}

void c300x_read_voicemail_info(
    const char *info_path,
    int *read,
    char *date,
    size_t date_len,
    long long *unix_time
)
{
    FILE *file;
    char line[256];
    int in_section = 0;

    *read = -1;
    if (date_len > 0) {
        date[0] = '\0';
    }
    *unix_time = 0;

    file = fopen(info_path, "r");
    if (file == NULL) {
        return;
    }
    while (fgets(line, sizeof(line), file) != NULL) {
        char *value = line;
        const char *trimmed;
        char *equals;

        trimmed = trim_ascii(value);
        if (trimmed[0] == '\0' || trimmed[0] == ';' || trimmed[0] == '#') {
            continue;
        }
        if (trimmed[0] == '[') {
            in_section = strcmp(trimmed, "[Message Information]") == 0;
            continue;
        }
        if (!in_section) {
            continue;
        }
        equals = strchr((char *)trimmed, '=');
        if (equals == NULL) {
            continue;
        }
        *equals = '\0';
        {
            const char *key = trim_ascii((char *)trimmed);
            const char *field = trim_ascii(equals + 1);
            if (strcasecmp(key, "Read") == 0) {
                if (strcmp(field, "0") == 0) {
                    *read = 0;
                } else if (strcmp(field, "1") == 0) {
                    *read = 1;
                }
            } else if (strcasecmp(key, "Date") == 0) {
                snprintf(date, date_len, "%s", field);
            } else if (strcasecmp(key, "UnixTime") == 0) {
                char *parse_end = NULL;
                long long parsed = strtoll(field, &parse_end, 10);
                if (parse_end != field && parsed > 0) {
                    *unix_time = parsed;
                }
            }
        }
    }
    fclose(file);
}

static int memo_path_is_directory(const char *path)
{
    C300X_MEMO_STAT_STRUCT st;

    return memo_stat_path(path, &st) == 0 && S_ISDIR(st.st_mode);
}

static int valid_utf8_text(const unsigned char *data, size_t len)
{
    size_t index = 0;

    while (index < len) {
        unsigned char ch = data[index];
        size_t extra = 0;
        unsigned int codepoint = 0;

        if (ch <= 0x7f) {
            if (ch == '\0' || (ch < 0x20 && ch != '\n' && ch != '\t')) {
                return 0;
            }
            index++;
            continue;
        }
        if ((ch & 0xe0) == 0xc0) {
            extra = 1;
            codepoint = ch & 0x1f;
            if (codepoint == 0) {
                return 0;
            }
        } else if ((ch & 0xf0) == 0xe0) {
            extra = 2;
            codepoint = ch & 0x0f;
        } else if ((ch & 0xf8) == 0xf0) {
            extra = 3;
            codepoint = ch & 0x07;
        } else {
            return 0;
        }
        if (index + extra >= len) {
            return 0;
        }
        for (size_t offset = 1; offset <= extra; offset++) {
            unsigned char next = data[index + offset];
            if ((next & 0xc0) != 0x80) {
                return 0;
            }
            codepoint = (codepoint << 6) | (next & 0x3f);
        }
        if (
            (extra == 1 && codepoint < 0x80)
            || (extra == 2 && codepoint < 0x800)
            || (extra == 3 && codepoint < 0x10000)
            || codepoint > 0x10ffff
            || (codepoint >= 0xd800 && codepoint <= 0xdfff)
        ) {
            return 0;
        }
        index += extra + 1;
    }
    return 1;
}

static size_t normalize_text_memo_bytes(unsigned char *data, size_t len)
{
    size_t read_index = 0;
    size_t write_index = 0;

    while (read_index < len) {
        if (data[read_index] == '\r') {
            data[write_index++] = '\n';
            read_index++;
            if (read_index < len && data[read_index] == '\n') {
                read_index++;
            }
            continue;
        }
        data[write_index++] = data[read_index++];
    }
    return write_index;
}

static int text_memo_has_visible_content(const unsigned char *data, size_t len)
{
    for (size_t index = 0; index < len; index++) {
        if (!isspace(data[index])) {
            return 1;
        }
    }
    return 0;
}

int c300x_text_memo_normalize(unsigned char *text, size_t *text_len)
{
    size_t len = *text_len;

    if (len == 0 || len > C300X_MAX_MEMO_TEXT_LEN) {
        return 0;
    }
    len = normalize_text_memo_bytes(text, len);
    text[len] = '\0';
    *text_len = len;
    return len > 0 && text_memo_has_visible_content(text, len) && valid_utf8_text(text, len);
}

/* The GUI writes message.txt into the records directory and bt_answering_machine
 * moves it into the new memo. The directory is open to every user: a name
 * found there is removed, never followed, and the file is made anew. */
int c300x_text_memo_stage(const char *records_dir, const char *owner_path,
                          const unsigned char *text, size_t text_len, char *error, size_t error_len)
{
    char path[C300X_MAX_PATH_LEN];
    C300X_MEMO_STAT_STRUCT owner;
    int have_owner = memo_stat_path(owner_path, &owner) == 0;
    int fd;
    size_t written = 0;

    if (!memo_path_is_directory(records_dir)) {
        if (mkdir(records_dir, 0777) != 0 && errno != EEXIST) {
            set_error(error, error_len, "memo_records_dir_missing");
            return 0;
        }
        if (chmod(records_dir, 0777) != 0 || (have_owner && chown(records_dir, owner.st_uid, owner.st_gid) != 0)) {
            set_error(error, error_len, "memo_records_dir_missing");
            return 0;
        }
    }
    if (!c300x_join_path(path, sizeof(path), records_dir, "message.txt")) {
        set_error(error, error_len, "invalid_memo_path");
        return 0;
    }
    if (unlink(path) != 0 && errno != ENOENT) {
        set_error(error, error_len, "memo_create_failed");
        return 0;
    }
    fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0644);
    if (fd < 0) {
        set_error(error, error_len, "memo_create_failed");
        return 0;
    }
    while (written < text_len) {
        ssize_t result = write(fd, text + written, text_len - written);
        if (result <= 0) {
            (void)close(fd);
            (void)unlink(path);
            set_error(error, error_len, "memo_create_failed");
            return 0;
        }
        written += (size_t)result;
    }
    if (fchmod(fd, 0644) != 0 || (have_owner && fchown(fd, owner.st_uid, owner.st_gid) != 0)) {
        (void)close(fd);
        (void)unlink(path);
        set_error(error, error_len, "memo_create_failed");
        return 0;
    }
    if (close(fd) != 0) {
        (void)unlink(path);
        set_error(error, error_len, "memo_create_failed");
        return 0;
    }
    return 1;
}

void c300x_text_memo_unstage(const char *records_dir)
{
    char path[C300X_MAX_PATH_LEN];

    if (c300x_join_path(path, sizeof(path), records_dir, "message.txt")) {
        (void)unlink(path);
    }
}

int c300x_text_memo_newest(const char *root, const int *numbers, int count)
{
    long long newest_time = -1;
    int newest = 0;

    for (int index = 0; index < count; index++) {
        char path[C300X_MAX_PATH_LEN];
        char date[8];
        int read;
        long long unix_time;

        if (snprintf(path, sizeof(path), "%s/memo_%d/msg_info.ini", root, numbers[index]) >= (int)sizeof(path)) {
            continue;
        }
        c300x_read_voicemail_info(path, &read, date, sizeof(date), &unix_time);
        if (unix_time > newest_time || (unix_time == newest_time && numbers[index] > newest)) {
            newest_time = unix_time;
            newest = numbers[index];
        }
    }
    return newest;
}
