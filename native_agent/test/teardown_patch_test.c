
#define _POSIX_C_SOURCE 200809L

#include "../src/media_teardown_patch.h"
#include "../src/audio_codec.h"
#include "../src/video_rtsp.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define TARGET_SIZE C300X_MEDIA_TEARDOWN_SIZE
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
    char stack[512];
    char linphone[512];
    char proc[512];
    char pid[512];
    char comm[512];
    char exe[512];
    char temporary_target[512];
    char second_pid[512];
    char second_comm[512];
    char second_exe[512];
    const char *tmp = getenv("TMPDIR");
    const char *stock_source;
    struct c300x_media_teardown_status status;
    char error[128];
    unsigned char *buffer;
    struct c300x_audio_codec_status codec;

    if (tmp == NULL || tmp[0] == '\0') {
        tmp = "/tmp";
    }
    snprintf(target, sizeof(target), "%s/c300x-teardown-target", tmp);
    snprintf(temporary_target, sizeof(temporary_target), "%s/c300x-teardown-target.tmp", tmp);
    snprintf(backup_dir, sizeof(backup_dir), "%s/c300x-teardown-backup", tmp);
    target_basename(basename, sizeof(basename));
    snprintf(backup, sizeof(backup), "%s/%s", backup_dir, basename);

    setenv("C300X_DEVICE_PATCH_NO_REMOUNT", "1", 1);
    setenv("C300X_MEDIA_TEARDOWN_TARGET", target, 1);
    setenv("C300X_MEDIA_TEARDOWN_BACKUP_DIR", backup_dir, 1);
    setenv("C300X_AUDIO_NO_REMOUNT", "1", 1);
    snprintf(stack, sizeof(stack), "%s/stack.xml", tmp);
    snprintf(linphone, sizeof(linphone), "%s/linphone.conf", tmp);
    snprintf(proc, sizeof(proc), "%s/proc", tmp);
    snprintf(pid, sizeof(pid), "%s/proc/123", tmp);
    snprintf(comm, sizeof(comm), "%s/proc/123/comm", tmp);
    snprintf(exe, sizeof(exe), "%s/proc/123/exe", tmp);
    snprintf(second_pid, sizeof(second_pid), "%s/proc/124", tmp);
    snprintf(second_comm, sizeof(second_comm), "%s/proc/124/comm", tmp);
    snprintf(second_exe, sizeof(second_exe), "%s/proc/124/exe", tmp);
    mkdir(proc, 0755);
    mkdir(pid, 0755);
    write_blob(comm, (const unsigned char *)basename, strlen(basename));
    setenv("C300X_MEDIA_TEARDOWN_PROC_ROOT", proc, 1);
    setenv("C300X_AUDIO_STACK_OPEN", stack, 1);
    setenv("C300X_AUDIO_LINPHONE_CONF", linphone, 1);
    setenv("C300X_AUDIO_BACKUP_DIR", backup_dir, 1);
    const char *stack_pcmu = "<enable_speex>0</enable_speex>\n";
    const char *linphone_pcmu = "[sound]\nrtp_ptnum=0\nrtp_map=PCMU/8000/1\n"
        "[audio_codec_0]\nmime=PCMU\nrate=8000\nenabled=1\n"
        "[audio_codec_1]\nmime=speex\nrate=8000\nenabled=0\n";
    write_blob(stack, (const unsigned char *)stack_pcmu, strlen(stack_pcmu));
    write_blob(linphone, (const unsigned char *)linphone_pcmu, strlen(linphone_pcmu));

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

    const unsigned char stock_word[] = {0xa8, 0x61, 0, 0};
    memcpy(buffer + DRAIN_0, stock_word, 4);
    memcpy(buffer + DRAIN_1, stock_word, 4);
    write_blob(target, buffer, TARGET_SIZE);
    check(!c300x_media_teardown_apply(&status, error, sizeof(error)),
          "valid stock words cannot authorize an unknown complete binary");
    check(!status.supported, "unknown binary is unsupported");
    check(access(backup, F_OK) != 0, "refused binary produces no backup");
    put_patched_drains(buffer);
    write_blob(target, buffer, TARGET_SIZE);
    check(!c300x_media_teardown_apply(&status, error, sizeof(error)),
          "valid patched words cannot authorize an unknown complete binary");
    check(!status.patched, "unknown binary cannot claim patched status");

    mkdir(backup_dir, 0755);
    write_blob(backup, buffer, TARGET_SIZE);
    check(!c300x_media_teardown_restore(&status, error, sizeof(error)),
          "restore refuses an unknown backup");
    free(buffer);
    check(!c300x_media_teardown_is_active(), "unreadable loaded executable is not active");

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
            write_blob(target, stock, stock_len);
            check(!c300x_media_teardown_apply(&status, error, sizeof(error)),
                  "apply refuses a corrupt existing backup");
            unlink(backup);
            /* Hard link models /proc/PID/exe retaining the old inode after rename. */
            check(link(target, exe) == 0, "retain the loaded original inode");
            check(c300x_media_teardown_read_status(&status) == 1, "stock status readable");
            check(strcmp(status.state, "stock") == 0, "stock target detected");

            /* PCMU no longer applies the drain patch: switching the codec leaves
             * the daemon exactly as it was. */
            check(c300x_audio_codec_apply(&codec, error, sizeof(error)) == 1,
                  "codec apply on a PCMU device succeeds without touching the daemon");
            check(!codec.changed, "codec apply makes no device-file change on PCMU");
            c300x_media_teardown_read_status(&status);
            check(strcmp(status.state, "stock") == 0, "codec apply leaves the daemon stock");
            check(status.patched == 0, "codec apply does not patch the daemon");

            /* Rolling back an unpatched daemon is a no-op. */
            check(c300x_audio_codec_rollback_teardown_patch(error, sizeof(error)) == 1,
                  "rollback is a no-op on a stock daemon");
            c300x_media_teardown_read_status(&status);
            check(strcmp(status.state, "stock") == 0, "no-op rollback leaves the daemon stock");

            /* Patch the daemon directly (the state a device from the coupled
             * release carries) and prove the startup rollback restores stock. */
            check(c300x_media_teardown_apply(&status, error, sizeof(error)) == 1,
                  "the raw patcher still produces a patched daemon to roll back");
            c300x_media_teardown_read_status(&status);
            check(status.patched == 1, "the daemon is patched before rollback");
            unlink(exe);
            check(link(target, exe) == 0, "the patched inode is the loaded one");
            check(c300x_audio_codec_rollback_teardown_patch(error, sizeof(error)) == 1,
                  "rollback restores a patched daemon");
            restored = read_blob(target, &restored_len);
            check(restored != NULL && restored_len == stock_len
                      && memcmp(restored, stock, stock_len) == 0,
                  "rollback is byte-identical to stock");
            free(restored);
            c300x_media_teardown_read_status(&status);
            check(status.patched == 0, "the daemon is stock after rollback");

            mkdir(second_pid, 0755);
            write_blob(second_comm, (const unsigned char *)basename, strlen(basename));
            write_blob(second_exe, stock, stock_len);
            check(!c300x_media_teardown_is_active(),
                  "a second unpatched daemon prevents claiming active protection");
            unlink(second_exe);
            unlink(second_comm);
            rmdir(second_pid);

            /* Restore the patched state for the status and diff checks below. */
            check(c300x_media_teardown_apply(&status, error, sizeof(error)) == 1,
                  "re-patch the daemon for the remaining status checks");
            unlink(exe);
            check(link(target, exe) == 0, "relink the patched inode");

            /* The patch state is a property of the file, so it must read back in
             * every codec mode. Deriving it inside the PCMU branch reported "not
             * installed" for a device whose running daemon was still patched. */
            const char *stack_speex = "<enable_speex>1</enable_speex>\n";
            const char *linphone_speex = "[sound]\nrtp_ptnum=110\nrtp_map=speex/8000/1\n"
                "[audio_codec_0]\nmime=PCMU\nrate=8000\nenabled=0\n"
                "[audio_codec_1]\nmime=speex\nrate=8000\nenabled=1\n";
            write_blob(stack, (const unsigned char *)stack_speex, strlen(stack_speex));
            write_blob(linphone, (const unsigned char *)linphone_speex, strlen(linphone_speex));
            c300x_audio_codec_read_status(&codec);
            check(strcmp(codec.state, "speex") == 0, "speex config reads back as speex");
            check(codec.teardown_patch_installed,
                  "speex still reports the installed drain patch");
            check(codec.teardown_patch_active,
                  "speex still reports the running patched daemon");
            check(!c300x_audio_codec_reboot_required(&codec, "speex"),
                  "a patched daemon under speex needs no reboot");

            /* "mount point is busy" on the closing read-only remount must not
             * turn a completed switch into a failure: the write already
             * happened, and HA would otherwise show the old codec. */
            char stub_dir[512];
            char stub[512];
            char path_value[1024];
            const char *old_path = getenv("PATH");
            const char *stub_body = "#!/bin/sh\ncase \"$*\" in *remount,ro*) exit 1;; esac\nexit 0\n";

            snprintf(stub_dir, sizeof(stub_dir), "%s/mountstub", tmp);
            mkdir(stub_dir, 0755);
            snprintf(stub, sizeof(stub), "%s/mount", stub_dir);
            write_blob(stub, (const unsigned char *)stub_body, strlen(stub_body));
            snprintf(path_value, sizeof(path_value), "%s:%s", stub_dir,
                     old_path != NULL ? old_path : "/usr/bin:/bin");
            setenv("PATH", path_value, 1);
            unsetenv("C300X_AUDIO_NO_REMOUNT");
            check(c300x_audio_codec_apply(&codec, error, sizeof(error)) == 1,
                  "a failed closing remount still reports the applied switch");
            check(codec.changed, "the applied switch is reported as a write");
            check(codec.remount_ro_failed,
                  "the unclosed read-only remount is reported, not swallowed");
            check(strcmp(codec.state, "pcmu") == 0, "the switch reached pcmu");
            setenv("C300X_AUDIO_NO_REMOUNT", "1", 1);
            if (old_path != NULL) {
                setenv("PATH", old_path, 1);
            } else {
                unsetenv("PATH");
            }
            unlink(stub);
            rmdir(stub_dir);

            write_blob(stack, (const unsigned char *)stack_pcmu, strlen(stack_pcmu));
            write_blob(linphone, (const unsigned char *)linphone_pcmu, strlen(linphone_pcmu));

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
            stock[0x100] ^= 1;
            write_blob(backup, stock, stock_len);
            check(!c300x_media_teardown_restore(&status, error, sizeof(error)),
                  "a one-byte corrupt backup cannot be restored");
            stock[0x100] ^= 1;
            write_blob(backup, stock, stock_len);
            check(c300x_media_teardown_restore(&status, error, sizeof(error)) == 1,
                  "restore succeeds for a real binary");
            restored = read_blob(target, &restored_len);
            check(restored != NULL && restored_len == stock_len
                      && memcmp(restored, stock, stock_len) == 0,
                  "restore is byte-identical to stock");
            free(restored);
            stock[0x100] ^= 1;
            write_blob(target, stock, stock_len);
            check(!c300x_media_teardown_apply(&status, error, sizeof(error)),
                  "a one-byte change outside the patch ranges is rejected");
            stock[0x100] ^= 1;
            const unsigned char mixed_word[] = {0x40, 0x0d, 0x03, 0};
            memcpy(stock + DRAIN_0, mixed_word, 4);
            write_blob(target, stock, stock_len);
            check(!c300x_media_teardown_apply(&status, error, sizeof(error)),
                  "a partly patched binary is rejected");
            memcpy(stock + DRAIN_0, stock_word, 4);
            write_blob(target, stock, stock_len - 1);
            check(!c300x_media_teardown_apply(&status, error, sizeof(error)),
                  "a truncated stock binary is rejected");
            free(stock);
        }
    } else {
        printf("skipped stock roundtrip (C300X_TEARDOWN_TEST_STOCK unset)\n");
    }

    unlink(target);
    unlink(exe);
    unlink(comm);
    rmdir(pid);
    rmdir(proc);
    unlink(stack);
    unlink(linphone);
    unlink(backup);
    rmdir(backup_dir);
    if (failures != 0) {
        fprintf(stderr, "%d check(s) failed\n", failures);
        return 1;
    }
    printf("media teardown patch test passed\n");
    return 0;
}
