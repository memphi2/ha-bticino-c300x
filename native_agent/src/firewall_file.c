#include "firewall_file.h"

#include "device_file.h"
#include "file_io.h"
#include "root_mount.h"
#include "string_util.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int c300x_firewall_read_file(const char *path, char *buffer, size_t buffer_len, int *exists)
{
    FILE *file;
    size_t read_len;
    int ok;

    if (exists != NULL) {
        *exists = 0;
    }
    if (buffer_len == 0) {
        return 0;
    }
    buffer[0] = '\0';
    file = fopen(path, "rb");
    if (file == NULL) {
        return errno == ENOENT;
    }
    if (exists != NULL) {
        *exists = 1;
    }
    read_len = fread(buffer, 1, buffer_len - 1, file);
    buffer[read_len] = '\0';
    ok = !ferror(file) && (read_len < buffer_len - 1 || fgetc(file) == EOF);
    fclose(file);
    return ok;
}

int c300x_firewall_write_file(const char *path, const char *content, mode_t new_mode)
{
    return mkdir_parent(path, 0755)
        && c300x_device_file_write_mode(path, content, strlen(content), new_mode)
        && c300x_device_file_sync_parents(path);
}

int c300x_firewall_backup_available(const char *backup_path)
{
    return backup_path != NULL && backup_path[0] != '\0' && access(backup_path, F_OK) == 0;
}

int c300x_firewall_backup_original(const char *backup_path, const char *content, int *written)
{
    size_t len = strlen(content) + 2;
    char *saved;
    int exists = 0, ok;

    *written = 0;
    if (c300x_firewall_backup_available(backup_path)) {
        return 1;
    }
    saved = malloc(len);
    ok = saved != NULL && c300x_firewall_write_file(backup_path, content, 0600)
        && c300x_firewall_read_file(backup_path, saved, len, &exists) && exists && strcmp(saved, content) == 0;
    free(saved);
    if (!ok) {
        (void)unlink(backup_path);
        return 0;
    }
    *written = 1;
    return 1;
}

static size_t length_without_final_newlines(const char *text)
{
    size_t len = strlen(text);
    while (len > 0 && text[len - 1] == '\n') {
        len--;
    }
    return len;
}

/* The block goes in with or without a blank line before it, so cutting it out
 * cannot tell the vendor's trailing blank lines from ours. A backup that
 * differs only in those is the original file, byte for byte. */
void c300x_firewall_use_matching_backup(const char *backup_path, char *desired, size_t desired_len)
{
    char *backup = calloc(1, desired_len);
    int backup_exists = 0;
    size_t len = length_without_final_newlines(desired);

    if (backup != NULL && desired[0] != '\0' && c300x_firewall_backup_available(backup_path)
        && c300x_firewall_read_file(backup_path, backup, desired_len, &backup_exists) && backup_exists
        && length_without_final_newlines(backup) == len && memcmp(backup, desired, len) == 0) {
        c300x_copy_string(desired, desired_len, backup);
    }
    free(backup);
}

int c300x_firewall_remount(const char *path, const char *mode)
{
    return path == NULL || strncmp(path, "/etc/", 5) != 0 || c300x_root_remount(mode);
}

int c300x_firewall_install(const char *path, const char *backup_path, const char *original,
                           const char *current, const char *desired, int *changed)
{
    int backup_written = 0, ok;

    *changed = 0;
    if (!c300x_firewall_remount(path, "rw")) {
        return 0;
    }
    ok = c300x_firewall_backup_original(backup_path, original, &backup_written)
        && (strcmp(current, desired) == 0 || c300x_firewall_write_file(path, desired, 0755));
    (void)c300x_firewall_remount(path, "ro");
    *changed = backup_written + (ok && strcmp(current, desired) != 0);
    return ok;
}
