#ifndef C300X_DEVICE_PATCH_IO_H
#define C300X_DEVICE_PATCH_IO_H

#include <stddef.h>
#include <sys/types.h>

struct c300x_patch_write {
    size_t offset;
    const unsigned char *data;
    size_t len;
};

struct c300x_patch_range {
    const char *name;
    size_t offset;
    size_t range_len;
    const char *expected_range_sha256;
    const char *patched_range_sha256;
    const struct c300x_patch_write *writes;
    size_t write_count;
};

int c300x_patch_file_mode(
    const char *path,
    mode_t *mode,
    uid_t *uid,
    gid_t *gid
);

int c300x_patch_ensure_parent_dir(const char *path);

int c300x_patch_copy_file_exact(const char *source, const char *target, mode_t mode);

int c300x_patch_remount_root(const char *mode);

int c300x_patch_read_file(const char *path, unsigned char **data, size_t *len);

int c300x_patch_range_matches(
    const unsigned char *data,
    size_t len,
    const struct c300x_patch_range *patch,
    const char *expected_sha256
);

#endif
