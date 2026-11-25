#include "proc_probe.h"
#include "file_io.h"

#include <ctype.h>
#include <dirent.h>
#include <stdio.h>
#include <string.h>

int c300x_process_cmdline_contains(const char *needle)
{
    DIR *directory;
    struct dirent *entry;

    directory = opendir("/proc");
    if (directory == NULL) {
        return 0;
    }
    while ((entry = readdir(directory)) != NULL) {
        char path[512];
        char buffer[512];
        FILE *file;
        size_t read_len;
        int is_pid = 1;

        for (const char *ptr = entry->d_name; *ptr != '\0'; ptr++) {
            if (!isdigit((unsigned char)*ptr)) {
                is_pid = 0;
                break;
            }
        }
        if (!is_pid) {
            continue;
        }
        if (snprintf(path, sizeof(path), "/proc/%s/cmdline", entry->d_name) >= (int)sizeof(path)) {
            continue;
        }
        file = fopen(path, "r");
        if (file == NULL) {
            continue;
        }
        read_len = fread(buffer, 1, sizeof(buffer) - 1, file);
        fclose(file);
        if (read_len == 0) {
            continue;
        }
        buffer[read_len] = '\0';
        for (size_t index = 0; index < read_len; index++) {
            if (buffer[index] == '\0') {
                buffer[index] = ' ';
            }
        }
        if (strstr(buffer, needle) != NULL) {
            closedir(directory);
            return 1;
        }
    }
    closedir(directory);
    return 0;
}

int c300x_file_contains_literal(const char *path, const char *needle)
{
    char buffer[8192];
    int truncated = 0;

    if (path == NULL || needle == NULL || needle[0] == '\0') {
        return 0;
    }
    if (!read_bounded_text_file(path, buffer, sizeof(buffer), &truncated)) {
        return 0;
    }
    return strstr(buffer, needle) != NULL;
}
