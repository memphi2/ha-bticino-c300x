/* The firewall writer sets a new script's mode on the temp file before the
 * rename and never chmods the path by name afterwards: /etc/init.d is
 * group-writable by bticino, so the name can be a symlink by then. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "../src/firewall_file.h"

static char g_dir[512];
static char g_swap_path[600];
static char g_swap_target[600];
static mode_t g_renamed_mode;
static int g_failures;

int __real_rename(const char *from, const char *to);

/* Records the temp file's mode at the rename and, when asked, swaps the
 * new name for a symlink right after it, as a bticino process could. */
int __wrap_rename(const char *from, const char *to)
{
    struct stat info;
    int result;

    if (strcmp(to, g_swap_path) == 0 && stat(from, &info) == 0) {
        g_renamed_mode = info.st_mode & 07777;
    }
    result = __real_rename(from, to);
    if (result == 0 && strcmp(to, g_swap_path) == 0 && g_swap_target[0] != '\0') {
        assert(unlink(to) == 0);
        assert(symlink(g_swap_target, to) == 0);
    }
    return result;
}

static const char *in_dir(char *out, size_t len, const char *name)
{
    assert(snprintf(out, len, "%s/%s", g_dir, name) < (int)len);
    return out;
}

static void put(const char *path, const char *content, mode_t mode)
{
    FILE *file = fopen(path, "wb");
    assert(file != NULL);
    assert(fputs(content, file) >= 0);
    assert(fclose(file) == 0);
    assert(chmod(path, mode) == 0);
}

static int same_text(const char *path, const char *want)
{
    char data[128];
    int exists = 0;
    return c300x_firewall_read_file(path, data, sizeof(data), &exists) && exists && strcmp(data, want) == 0;
}

static void check(int ok, const char *what)
{
    if (!ok) {
        fprintf(stderr, "FAIL: %s\n", what);
        g_failures++;
    }
}

/* A new script: the mode is on the temp file at the rename, and a symlink
 * swapped in after the rename does not get its target chmodded. */
static void new_file_race(void)
{
    char path[600], victim[600];
    struct stat info;

    in_dir(path, sizeof(path), "firewall-new");
    put(in_dir(victim, sizeof(victim), "victim"), "secret", 0600);
    assert(snprintf(g_swap_path, sizeof(g_swap_path), "%s", path) < (int)sizeof(g_swap_path));
    assert(snprintf(g_swap_target, sizeof(g_swap_target), "%s", victim) < (int)sizeof(g_swap_target));
    g_renamed_mode = 0;
    (void)c300x_firewall_write_file(path, "#!/bin/sh\n", 0750);
    check(g_renamed_mode == 0750, "a new script has its mode before the rename");
    check(stat(victim, &info) == 0 && (info.st_mode & 07777) == 0600,
          "a symlink swapped in after the rename does not get its target chmodded");
    check(same_text(victim, "secret"), "the swapped-in symlink target is not written");
    g_swap_path[0] = '\0';
    g_swap_target[0] = '\0';
}

/* A dangling symlink at the path: replaced by the new script with
 * new_mode, its target is not created. */
static void dangling_symlink(void)
{
    char path[600], target[600];
    struct stat info;

    in_dir(target, sizeof(target), "dangling-target");
    assert(symlink(target, in_dir(path, sizeof(path), "firewall-dangling")) == 0);
    check(c300x_firewall_write_file(path, "#!/bin/sh\n", 0750), "a dangling symlink is replaced");
    check(lstat(path, &info) == 0 && S_ISREG(info.st_mode) && (info.st_mode & 07777) == 0750,
          "the path is a new 0750 script");
    check(same_text(path, "#!/bin/sh\n"), "the new script holds the content");
    check(access(target, F_OK) != 0, "the dangling symlink target is not created");
}

/* An existing script keeps its mode. */
static void existing_file(void)
{
    char path[600];
    struct stat info;

    put(in_dir(path, sizeof(path), "firewall-existing"), "old\n", 0500);
    check(c300x_firewall_write_file(path, "new\n", 0750), "an existing script is replaced");
    check(stat(path, &info) == 0 && (info.st_mode & 07777) == 0500, "an existing script keeps its mode");
    check(same_text(path, "new\n"), "the replaced script holds the content");
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    assert(snprintf(g_dir, sizeof(g_dir), "%s", argv[1]) < (int)sizeof(g_dir));
    new_file_race();
    dangling_symlink();
    existing_file();
    return g_failures != 0;
}
