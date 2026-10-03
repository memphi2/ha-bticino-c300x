
#define _POSIX_C_SOURCE 200809L

#include "../src/media_teardown_patch.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define TARGET_SIZE 0xe000u
#define DRAIN_0 0x5ee0u
#define DRAIN_1 0xdd0cu

static int failures;

static void target_basename(char *out, size_t out_len)
{
    static const struct { size_t offset; char value; } replacements[] = {
        {0, 'b'}, {1, 't'}, {3, 'a'}, {4, 'v'},
        {6, 'm'}, {7, 'e'}, {8, 'd'}, {9, 'i'}, {10, 'a'},
    };
    snprintf(out, out_len, "%s", "??_??_?????");
    for (size_t i = 0; i < sizeof(replacements) / sizeof(replacements[0]); i++) {
        out[replacements[i].offset] = replacements[i].value;
    }
}

static void check(int condition, const char *what)
{
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", what);
        failures++;
    }
}

static void write_blob(const char *path, const unsigned char *data, size_t len)
{
    FILE *fp = fopen(path, "wb");

    if (fp == NULL || fwrite(data, 1, len, fp) != len) {
        fprintf(stderr, "cannot write %s\n", path);
        exit(2);
    }
    fclose(fp);
    chmod(path, 0755);
}

static unsigned char *read_blob(const char *path, size_t *len)
{
    FILE *fp = fopen(path, "rb");
    unsigned char *data;
    long size;

    if (fp == NULL) {
        return NULL;
    }
    fseek(fp, 0, SEEK_END);
    size = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    data = malloc((size_t)size);
    if (data == NULL || fread(data, 1, (size_t)size, fp) != (size_t)size) {
        fclose(fp);
        free(data);
        return NULL;
    }
    fclose(fp);
    *len = (size_t)size;
    return data;
}

static void put_patched_drains(unsigned char *buffer)
{
    static const unsigned char patched[4] = {0x40, 0x0d, 0x03, 0x00};

    memcpy(buffer + DRAIN_0, patched, sizeof(patched));
    memcpy(buffer + DRAIN_1, patched, sizeof(patched));
}

int main(void)
{
    char target[512];
    char backup_dir[512];
    char backup[512];
    char basename[32];
    const char *tmp = getenv("TMPDIR");
    const char *stock_source;
    struct c300x_media_teardown_status status;
    char error[128];
    unsigned char *buffer;
    struct stat before;
    struct stat after;

    if (tmp == NULL || tmp[0] == '\0') {
        tmp = "/tmp";
    }
    snprintf(target, sizeof(target), "%s/c300x-teardown-target", tmp);
    snprintf(backup_dir, sizeof(backup_dir), "%s/c300x-teardown-backup", tmp);
    target_basename(basename, sizeof(basename));
    snprintf(backup, sizeof(backup), "%s/%s", backup_dir, basename);

    setenv("C300X_DEVICE_PATCH_NO_REMOUNT", "1", 1);
    setenv("C300X_MEDIA_TEARDOWN_TARGET", target, 1);
    setenv("C300X_MEDIA_TEARDOWN_BACKUP_DIR", backup_dir, 1);

    unlink(target);
    check(c300x_media_teardown_read_status(&status) == 0, "missing target reports failure");
    check(strcmp(status.state, "missing") == 0, "missing target state");
    check(c300x_media_teardown_apply(&status, error, sizeof(error)) == 0,
          "apply refuses a missing target");

    buffer = calloc(1, TARGET_SIZE);
    if (buffer == NULL) {
        return 2;
    }
    memset(buffer + DRAIN_0, 0x11, 4);
    memset(buffer + DRAIN_1, 0x22, 4);
    write_blob(target, buffer, TARGET_SIZE);
    check(c300x_media_teardown_read_status(&status) == 1, "unsupported target returns status");
    check(strcmp(status.state, "unsupported") == 0, "unsupported target state");
    check(status.patched == 0, "unsupported target is not patched");
    check(c300x_media_teardown_apply(&status, error, sizeof(error)) == 0,
          "apply refuses an unrecognised target");

    put_patched_drains(buffer);
    write_blob(target, buffer, TARGET_SIZE);
    check(c300x_media_teardown_read_status(&status) == 1, "patched target returns status");
    check(strcmp(status.state, "patched") == 0, "patched target state");
    check(status.patched == 1, "patched flag set");
    check(stat(target, &before) == 0, "stat before idempotent apply");
    sleep(1);
    check(c300x_media_teardown_apply(&status, error, sizeof(error)) == 1,
          "apply is idempotent on a patched target");
    check(stat(target, &after) == 0, "stat after idempotent apply");
    check(before.st_mtime == after.st_mtime, "idempotent apply performs no write");

    mkdir(backup_dir, 0755);
    write_blob(backup, buffer, TARGET_SIZE);
    memset(buffer + DRAIN_0, 0x33, 4);
    write_blob(target, buffer, TARGET_SIZE);
    check(c300x_media_teardown_restore(&status, error, sizeof(error)) == 1, "restore succeeds");
    check(strcmp(status.state, "patched") == 0, "restored target is the backup");
    free(buffer);

    {
        char stub_dir[512];
        char stub[512];
        char mount_log[512];
        char path_value[1600];
        const char *old_path = getenv("PATH");
        FILE *fp;
        struct stat log_stat;

        snprintf(stub_dir, sizeof(stub_dir), "%s/c300x-teardown-stub", tmp);
        mkdir(stub_dir, 0755);
        snprintf(stub, sizeof(stub), "%s/mount", stub_dir);
        snprintf(mount_log, sizeof(mount_log), "%s/c300x-teardown-mount.log", tmp);
        unlink(mount_log);
        fp = fopen(stub, "wb");
        if (fp != NULL) {
            fprintf(fp, "#!/bin/sh\necho \"$@\" >> \"%s\"\nexit 0\n", mount_log);
            fclose(fp);
            chmod(stub, 0755);
            snprintf(path_value, sizeof(path_value), "%s:%s", stub_dir,
                     old_path != NULL ? old_path : "/bin");
            setenv("PATH", path_value, 1);
            unsetenv("C300X_DEVICE_PATCH_NO_REMOUNT");
            check(c300x_media_teardown_apply(&status, error, sizeof(error)) == 1,
                  "apply stays idempotent without the remount override");
            check(stat(mount_log, &log_stat) != 0,
                  "an already-patched target triggers no remount at all");
            setenv("C300X_DEVICE_PATCH_NO_REMOUNT", "1", 1);
            unlink(stub);
            rmdir(stub_dir);
            unlink(mount_log);
        }
    }

    stock_source = getenv("C300X_TEARDOWN_TEST_STOCK");
    if (stock_source != NULL && stock_source[0] != '\0') {
        size_t stock_len = 0;
        size_t patched_len = 0;
        size_t restored_len = 0;
        unsigned char *stock = read_blob(stock_source, &stock_len);
        unsigned char *patched_data;
        unsigned char *restored;
        size_t differing = 0;

        check(stock != NULL, "stock source readable");
        if (stock != NULL) {
            unlink(backup);
            write_blob(target, stock, stock_len);
            check(c300x_media_teardown_read_status(&status) == 1, "stock status readable");
            check(strcmp(status.state, "stock") == 0, "stock target detected");
            check(c300x_media_teardown_apply(&status, error, sizeof(error)) == 1,
                  "apply patches a stock target");
            check(status.patched == 1, "stock target becomes patched");

            patched_data = read_blob(target, &patched_len);
            check(patched_data != NULL && patched_len == stock_len,
                  "patched file keeps its size");
            if (patched_data != NULL) {
                for (size_t i = 0; i < stock_len; i++) {
                    if (stock[i] != patched_data[i]) {
                        differing++;
                    }
                }
                check(differing == 6, "exactly six bytes change");
                free(patched_data);
            }
            check(c300x_media_teardown_restore(&status, error, sizeof(error)) == 1,
                  "restore succeeds for a real binary");
            restored = read_blob(target, &restored_len);
            check(restored != NULL && restored_len == stock_len
                      && memcmp(restored, stock, stock_len) == 0,
                  "restore is byte-identical to stock");
            free(restored);
            free(stock);
        }
    } else {
        printf("skipped stock roundtrip (C300X_TEARDOWN_TEST_STOCK unset)\n");
    }

    unlink(target);
    unlink(backup);
    rmdir(backup_dir);
    if (failures != 0) {
        fprintf(stderr, "%d check(s) failed\n", failures);
        return 1;
    }
    printf("media teardown patch test passed\n");
    return 0;
}
