#ifndef C300X_FILE_IO_H
#define C300X_FILE_IO_H

#include <stddef.h>
#include <sys/types.h>

int read_bounded_text_file(
    const char *path,
    char *out,
    size_t out_len,
    int *truncated
);

int path_parent_inplace(char *path);

int mkdir_p(const char *path, mode_t mode);

int mkdir_parent(const char *path, mode_t mode);

int remove_tree(const char *path);

int write_binary_chunk(
    const char *path,
    const unsigned char *data,
    size_t data_len,
    long offset,
    mode_t mode
);

int copy_binary_file(const char *source, const char *target, mode_t mode);

int file_content_matches(const char *source, const char *target);

int copy_binary_file_if_changed(
    const char *source,
    const char *target,
    mode_t mode,
    int *changed
);

int sha256_hex_matches(const char *path, const char *expected);

#endif
