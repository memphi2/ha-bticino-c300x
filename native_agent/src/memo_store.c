#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif

#include "memo_store.h"

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <sys/stat.h>
#include <time.h>
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

static int memo_lstat_path(const char *path, C300X_MEMO_STAT_STRUCT *status)
{
#ifdef __arm__
    return (int)syscall(SYS_lstat64, path, status);
#else
    return lstat(path, status);
#endif
}

static void set_error(char *error, size_t error_len, const char *value)
{
    if (error_len == 0) {
        return;
    }
    snprintf(error, error_len, "%s", value);
}

static int memo_path_exists(const char *path)
{
    C300X_MEMO_STAT_STRUCT st;

    return memo_stat_path(path, &st) == 0;
}

static int memo_path_is_directory(const char *path)
{
    C300X_MEMO_STAT_STRUCT st;

    return memo_stat_path(path, &st) == 0 && S_ISDIR(st.st_mode);
}

static int memo_remove_tree(const char *path)
{
    DIR *directory;
    struct dirent *entry;

    directory = opendir(path);
    if (directory == NULL) {
        return errno == ENOENT;
    }
    while ((entry = readdir(directory)) != NULL) {
        char child[C300X_MAX_PATH_LEN];
        C300X_MEMO_STAT_STRUCT st;

        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        if (snprintf(child, sizeof(child), "%s/%s", path, entry->d_name) >= (int)sizeof(child)) {
            closedir(directory);
            return 0;
        }
        if (memo_lstat_path(child, &st) != 0) {
            closedir(directory);
            return 0;
        }
        if (S_ISDIR(st.st_mode)) {
            if (!memo_remove_tree(child)) {
                closedir(directory);
                return 0;
            }
        } else if (unlink(child) != 0) {
            closedir(directory);
            return 0;
        }
    }
    closedir(directory);
    return rmdir(path) == 0 || errno == ENOENT;
}

static int write_file_bytes(
    const char *path,
    const unsigned char *data,
    size_t len,
    mode_t mode
)
{
    FILE *file = fopen(path, "wb");

    if (file == NULL) {
        return 0;
    }
    if (len > 0 && fwrite(data, 1, len, file) != len) {
        (void)fclose(file);
        return 0;
    }
    if (fclose(file) != 0) {
        return 0;
    }
    (void)chmod(path, mode);
    return 1;
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

static int next_text_memo_entry_name(
    const char *root,
    int max_memos,
    char *entry_name,
    size_t entry_name_len
)
{
    int max_entries = max_memos;

    if (max_entries <= 0 || max_entries > C300X_MAX_VOICEMAIL_MESSAGES) {
        max_entries = C300X_MAX_VOICEMAIL_MESSAGES;
    }
    for (int number = 1; number <= max_entries; number++) {
        char candidate_name[C300X_MAX_VOICEMAIL_ID_LEN];
        char candidate_path[C300X_MAX_PATH_LEN];

        snprintf(candidate_name, sizeof(candidate_name), "memo_%d", number);
        if (snprintf(candidate_path, sizeof(candidate_path), "%s/%s", root, candidate_name) >= (int)sizeof(candidate_path)) {
            return 0;
        }
        if (!memo_path_exists(candidate_path)) {
            snprintf(entry_name, entry_name_len, "%s", candidate_name);
            return 1;
        }
    }
    return 0;
}

static void format_memo_date(time_t now, char *date, size_t date_len)
{
    struct tm tm_value;

    if (date_len == 0) {
        return;
    }
    date[0] = '\0';
    if (localtime_r(&now, &tm_value) == NULL) {
        return;
    }
    strftime(date, date_len, "%d/%m/%Y %H:%M", &tm_value);
}

int c300x_text_memo_create(
    const char *root,
    int max_memos,
    const unsigned char *text,
    size_t text_len,
    int read,
    char *entry_name,
    size_t entry_name_len,
    char *error,
    size_t error_len
)
{
    unsigned char normalized[C300X_MAX_MEMO_TEXT_LEN + 1];
    char entry_path[C300X_MAX_PATH_LEN];
    char tmp_path[C300X_MAX_PATH_LEN];
    char message_path[C300X_MAX_PATH_LEN];
    char info_path[C300X_MAX_PATH_LEN];
    char info_content[256];
    char date[64];
    time_t now;

    if (entry_name_len > 0) {
        entry_name[0] = '\0';
    }
    if (root == NULL || root[0] == '\0' || !memo_path_is_directory(root)) {
        set_error(error, error_len, "memos_dir_missing");
        return 0;
    }
    if (text == NULL || text_len == 0 || text_len > C300X_MAX_MEMO_TEXT_LEN) {
        set_error(error, error_len, "invalid_text");
        return 0;
    }
    memcpy(normalized, text, text_len);
    text_len = normalize_text_memo_bytes(normalized, text_len);
    normalized[text_len] = '\0';
    if (
        text_len == 0
        || text_len > C300X_MAX_MEMO_TEXT_LEN
        || !text_memo_has_visible_content(normalized, text_len)
        || !valid_utf8_text(normalized, text_len)
    ) {
        set_error(error, error_len, "invalid_text");
        return 0;
    }
    if (!next_text_memo_entry_name(root, max_memos, entry_name, entry_name_len)) {
        set_error(error, error_len, "memo_store_full");
        return 0;
    }
    if (snprintf(entry_path, sizeof(entry_path), "%s/%s", root, entry_name) >= (int)sizeof(entry_path)) {
        set_error(error, error_len, "invalid_memo_path");
        return 0;
    }
    if (snprintf(tmp_path, sizeof(tmp_path), "%s/.%s.tmp.%ld", root, entry_name, (long)getpid()) >= (int)sizeof(tmp_path)) {
        set_error(error, error_len, "invalid_memo_path");
        return 0;
    }
    (void)memo_remove_tree(tmp_path);
    if (mkdir(tmp_path, 0755) != 0) {
        set_error(error, error_len, "memo_create_failed");
        return 0;
    }
    if (
        snprintf(message_path, sizeof(message_path), "%s/message.txt", tmp_path) >= (int)sizeof(message_path)
        || snprintf(info_path, sizeof(info_path), "%s/msg_info.ini", tmp_path) >= (int)sizeof(info_path)
    ) {
        (void)memo_remove_tree(tmp_path);
        set_error(error, error_len, "invalid_memo_path");
        return 0;
    }
    now = time(NULL);
    format_memo_date(now, date, sizeof(date));
    snprintf(
        info_content,
        sizeof(info_content),
        "[Message Information]\nRead=%d\nDate=%s\nUnixTime=%lld\nMediaType=1\n",
        read ? 1 : 0,
        date,
        (long long)now
    );
    if (
        !write_file_bytes(message_path, normalized, text_len, 0644)
        || !write_file_bytes(info_path, (const unsigned char *)info_content, strlen(info_content), 0644)
    ) {
        (void)memo_remove_tree(tmp_path);
        set_error(error, error_len, "memo_create_failed");
        return 0;
    }
    if (rename(tmp_path, entry_path) != 0) {
        (void)memo_remove_tree(tmp_path);
        set_error(error, error_len, "memo_create_failed");
        return 0;
    }
    set_error(error, error_len, "ok");
    return 1;
}
