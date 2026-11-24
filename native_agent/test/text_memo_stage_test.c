/* message.txt is staged in a records directory under the world-writable
 * /var/tmp: no name found there is followed, and nothing outside it is
 * chmodded, chowned, written or removed. */
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "../src/memo_store.h"

static char g_dir[512];
static const unsigned char TEXT[] = "Bin gleich da";

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
    FILE *file = fopen(path, "rb");
    size_t got;
    if (file == NULL) {
        return 0;
    }
    got = fread(data, 1, sizeof(data) - 1, file);
    fclose(file);
    data[got] = '\0';
    return strcmp(data, want) == 0;
}

static int stage(const char *records, const char *owner, char *error, size_t error_len)
{
    error[0] = '\0';
    return c300x_text_memo_stage(records, owner, TEXT, sizeof(TEXT) - 1, error, error_len);
}

static int g_failures;

static void check(int ok, const char *what)
{
    if (!ok) {
        fprintf(stderr, "FAIL: %s\n", what);
        g_failures++;
    }
}

/* A symlink to a file at the records name: refused, the file keeps its mode,
 * owner and content (the old code chmodded it to 0777 and chowned it). */
static void symlink_to_file(const char *owner)
{
    char records[600], victim[600], error[64];
    struct stat before, after;

    put(in_dir(victim, sizeof(victim), "victim"), "secret", 0600);
    assert(symlink(victim, in_dir(records, sizeof(records), "records-file-link")) == 0);
    assert(stat(victim, &before) == 0);
    check(!stage(records, owner, error, sizeof(error)), "a symlink to a file is refused");
    check(strcmp(error, "memo_records_dir_missing") == 0, "the refusal says memo_records_dir_missing");
    assert(stat(victim, &after) == 0);
    check((after.st_mode & 07777) == 0600, "the symlink target keeps its mode");
    check(after.st_uid == before.st_uid && after.st_gid == before.st_gid, "the symlink target keeps its owner");
    check(same_text(victim, "secret"), "the symlink target keeps its content");
}

/* A symlink to a directory: refused, nothing created or removed in there,
 * and unstaging through it removes nothing either. */
static void symlink_to_directory(const char *owner)
{
    char records[600], elsewhere[600], inside[700], error[64];

    assert(mkdir(in_dir(elsewhere, sizeof(elsewhere), "elsewhere"), 0755) == 0);
    assert(snprintf(inside, sizeof(inside), "%s/message.txt", elsewhere) < (int)sizeof(inside));
    put(inside, "keep", 0600);
    assert(symlink(elsewhere, in_dir(records, sizeof(records), "records-dir-link")) == 0);
    check(!stage(records, owner, error, sizeof(error)), "a symlink to a directory is refused");
    check(strcmp(error, "memo_records_dir_missing") == 0, "the refusal says memo_records_dir_missing");
    check(same_text(inside, "keep"), "the file behind the symlinked directory is untouched");
    c300x_text_memo_unstage(records);
    check(same_text(inside, "keep"), "unstaging does not follow the symlinked directory");
}

/* A missing records directory is made 0777 whatever the umask, the text
 * lands in a new 0644 message.txt, and unstaging removes it. */
static void new_directory(const char *owner)
{
    char records[600], staged[700], error[64];
    struct stat info;

    in_dir(records, sizeof(records), "records");
    assert(snprintf(staged, sizeof(staged), "%s/message.txt", records) < (int)sizeof(staged));
    check(stage(records, owner, error, sizeof(error)), "a missing records directory is made");
    check(lstat(records, &info) == 0 && S_ISDIR(info.st_mode) && (info.st_mode & 07777) == 0777,
          "the new records directory is a 0777 directory");
    check(lstat(staged, &info) == 0 && S_ISREG(info.st_mode) && (info.st_mode & 07777) == 0644,
          "message.txt is a regular 0644 file");
    check(same_text(staged, (const char *)TEXT), "message.txt holds the text");
    c300x_text_memo_unstage(records);
    check(access(staged, F_OK) != 0, "unstaging removes message.txt");
}

/* An existing directory keeps its mode; a symlink left at message.txt is
 * replaced, its target is not written. */
static void existing_directory(const char *owner)
{
    char records[600], staged[700], victim[600], error[64];
    struct stat info;

    assert(mkdir(in_dir(records, sizeof(records), "records-existing"), 0700) == 0);
    assert(chmod(records, 0750) == 0);
    put(in_dir(victim, sizeof(victim), "staged-victim"), "secret", 0600);
    assert(snprintf(staged, sizeof(staged), "%s/message.txt", records) < (int)sizeof(staged));
    assert(symlink(victim, staged) == 0);
    check(stage(records, owner, error, sizeof(error)), "an existing records directory is used");
    check(lstat(records, &info) == 0 && (info.st_mode & 07777) == 0750, "an existing directory keeps its mode");
    check(lstat(staged, &info) == 0 && S_ISREG(info.st_mode), "the symlink at message.txt is replaced");
    check(same_text(staged, (const char *)TEXT), "message.txt holds the text");
    check(same_text(victim, "secret"), "the old symlink target is not written");
}

int main(int argc, char **argv)
{
    char owner[600];

    assert(argc == 2);
    assert(snprintf(g_dir, sizeof(g_dir), "%s", argv[1]) < (int)sizeof(g_dir));
    umask(022);
    put(in_dir(owner, sizeof(owner), "owner"), "", 0644);
    symlink_to_file(owner);
    symlink_to_directory(owner);
    new_directory(owner);
    existing_directory(owner);
    return g_failures != 0;
}
