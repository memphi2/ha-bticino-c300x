#include "file_io.h"
#include "c300x_agent.h"
#include "sha256.h"
#include "string_util.h"
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int file_size_matches(const char *path, long expected_size);

int read_bounded_text_file(
    const char *path,
    char *out,
    size_t out_len,
    int *truncated
)
{
    FILE *file;
    size_t read_len;

    if (truncated != NULL) {
        *truncated = 0;
    }
    if (out_len == 0) {
        return 0;
    }
    out[0] = '\0';
    if (path == NULL || path[0] == '\0') {
        return 0;
    }
    file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    read_len = fread(out, 1, out_len - 1, file);
    out[read_len] = '\0';
    if (truncated != NULL && read_len == out_len - 1 && fgetc(file) != EOF) {
        *truncated = 1;
    }
    fclose(file);
    while (read_len > 0 && (out[read_len - 1] == '\n' || out[read_len - 1] == '\r')) {
        out[--read_len] = '\0';
    }
    return read_len > 0;
}

int path_parent_inplace(char *path)
{
    size_t len;
    char *slash;

    if (path == NULL || path[0] == '\0') {
        return 0;
    }
    len = strlen(path);
    while (len > 1 && path[len - 1] == '/') {
        path[len - 1] = '\0';
        len--;
    }
    slash = strrchr(path, '/');
    if (slash == NULL) {
        return 0;
    }
    if (slash == path) {
        path[1] = '\0';
        return 1;
    }
    *slash = '\0';
    return 1;
}

int mkdir_p(const char *path, mode_t mode)
{
    char buffer[C300X_MAX_PATH_LEN];
    size_t len;

    if (path == NULL || path[0] != '/') {
        return 0;
    }
    if (snprintf(buffer, sizeof(buffer), "%s", path) >= (int)sizeof(buffer)) {
        return 0;
    }
    len = strlen(buffer);
    while (len > 1 && buffer[len - 1] == '/') {
        buffer[--len] = '\0';
    }
    for (char *ptr = buffer + 1; *ptr != '\0'; ptr++) {
        if (*ptr != '/') {
            continue;
        }
        *ptr = '\0';
        if (mkdir(buffer, mode) != 0 && errno != EEXIST) {
            *ptr = '/';
            return 0;
        }
        *ptr = '/';
    }
    return mkdir(buffer, mode) == 0 || errno == EEXIST;
}

int mkdir_parent(const char *path, mode_t mode)
{
    char parent[C300X_MAX_PATH_LEN];

    if (snprintf(parent, sizeof(parent), "%s", path) >= (int)sizeof(parent)) {
        return 0;
    }
    if (!path_parent_inplace(parent)) {
        return 0;
    }
    return mkdir_p(parent, mode);
}

int remove_tree(const char *path)
{
    DIR *directory;
    struct dirent *entry;

    directory = opendir(path);
    if (directory == NULL) {
        return errno == ENOENT;
    }
    while ((entry = readdir(directory)) != NULL) {
        char child[C300X_MAX_PATH_LEN];
        DIR *child_directory;

        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        if (!c300x_join_path(child, sizeof(child), path, entry->d_name)) {
            closedir(directory);
            return 0;
        }
        child_directory = opendir(child);
        if (child_directory != NULL) {
            closedir(child_directory);
            if (!remove_tree(child)) {
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

int write_binary_chunk(
    const char *path,
    const unsigned char *data,
    size_t data_len,
    long offset,
    mode_t mode
)
{
    FILE *file;
    int fd;

    if (path == NULL || path[0] == '\0' || offset < 0) {
        return 0;
    }
    if (!mkdir_parent(path, 0755)) {
        return 0;
    }
    if (offset == 0) {
        file = fopen(path, "wb");
    } else {
        if (!file_size_matches(path, offset)) {
            return 0;
        }
        file = fopen(path, "ab");
    }
    if (file == NULL) {
        return 0;
    }
    if (data_len > 0 && fwrite(data, 1, data_len, file) != data_len) {
        (void)fclose(file);
        return 0;
    }
    fd = fileno(file);
    if (fd >= 0) {
        (void)fchmod(fd, mode);
    }
    if (fclose(file) != 0) {
        return 0;
    }
    return 1;
}

int copy_binary_file(const char *source, const char *target, mode_t mode)
{
    char temporary_path[C300X_MAX_PATH_LEN + 8];
    unsigned char buffer[4096];
    FILE *in;
    FILE *out;
    size_t read_len;
    int out_fd;

    if (!mkdir_parent(target, 0755)) {
        return 0;
    }
    if (snprintf(temporary_path, sizeof(temporary_path), "%s.tmp", target) >= (int)sizeof(temporary_path)) {
        return 0;
    }
    in = fopen(source, "rb");
    if (in == NULL) {
        return 0;
    }
    out = fopen(temporary_path, "wb");
    if (out == NULL) {
        fclose(in);
        return 0;
    }
    while ((read_len = fread(buffer, 1, sizeof(buffer), in)) > 0) {
        if (fwrite(buffer, 1, read_len, out) != read_len) {
            fclose(in);
            fclose(out);
            (void)unlink(temporary_path);
            return 0;
        }
    }
    if (ferror(in)) {
        fclose(in);
        fclose(out);
        (void)unlink(temporary_path);
        return 0;
    }
    out_fd = fileno(out);
    if (out_fd >= 0) {
        (void)fchmod(out_fd, mode);
    }
    {
        int close_in = fclose(in);
        int close_out = fclose(out);
        if (close_in != 0 || close_out != 0) {
            (void)unlink(temporary_path);
            return 0;
        }
    }
    if (rename(temporary_path, target) != 0) {
        (void)unlink(temporary_path);
        return 0;
    }
    return 1;
}

int file_content_matches(const char *source, const char *target)
{
    char source_sha[65];
    char target_sha[65];

    if (
        !c300x_sha256_file_hex(source, source_sha, sizeof(source_sha))
        || !c300x_sha256_file_hex(target, target_sha, sizeof(target_sha))
    ) {
        return 0;
    }
    return constant_time_equal(source_sha, strlen(source_sha), target_sha);
}

int copy_binary_file_if_changed(
    const char *source,
    const char *target,
    mode_t mode,
    int *changed
)
{
    if (changed != NULL) {
        *changed = 0;
    }
    if (file_content_matches(source, target)) {
        return 1;
    }
    if (!copy_binary_file(source, target, mode)) {
        return 0;
    }
    if (changed != NULL) {
        *changed = 1;
    }
    return 1;
}

int sha256_hex_matches(const char *path, const char *expected)
{
    char actual[65];

    if (expected == NULL || strlen(expected) != 64) {
        return 0;
    }
    if (!c300x_sha256_file_hex(path, actual, sizeof(actual))) {
        return 0;
    }
    return constant_time_equal(actual, strlen(actual), expected);
}

static int file_size_matches(const char *path, long expected_size)
{
    FILE *file;
    long size;

    file = fopen(path, "rb");
    if (file == NULL) {
        return 0;
    }
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return 0;
    }
    size = ftell(file);
    fclose(file);
    if (size < 0) {
        return 0;
    }
    return size == expected_size;
}
