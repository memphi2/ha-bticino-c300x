#include "media_teardown_patch.h"

#include "c300x_agent.h"
#include "sha256.h"

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int c300x_media_teardown_is_active(void)
{
    const char *root = getenv("C300X_MEDIA_TEARDOWN_PROC_ROOT");
    char name[32];
    char path[C300X_MAX_PATH_LEN];
    char comm[64];
    char digest[65];
    int found = 0;
    int valid = 1;

    if (root == NULL || root[0] == '\0') {
        root = "/proc";
    }
    if (!c300x_media_teardown_target_name(name, sizeof(name))) {
        return 0;
    }
    DIR *directory = opendir(root);
    if (directory == NULL) {
        return 0;
    }
    for (;;) {
        errno = 0;
        struct dirent *entry = readdir(directory);
        if (entry == NULL) {
            valid = errno == 0;
            break;
        }
        if (!isdigit((unsigned char)entry->d_name[0])
            || strspn(entry->d_name, "0123456789") != strlen(entry->d_name)) {
            continue;
        }
        if (snprintf(path, sizeof(path), "%s/%s/comm", root, entry->d_name) >= (int)sizeof(path)) {
            valid = 0;
            break;
        }
        FILE *file = fopen(path, "r");
        if (file == NULL) {
            continue;
        }
        int read_ok = fgets(comm, sizeof(comm), file) != NULL;
        fclose(file);
        if (!read_ok) {
            continue;
        }
        comm[strcspn(comm, "\r\n")] = '\0';
        if (strcmp(comm, name) != 0) {
            continue;
        }
        /* /proc/PID/exe refers to the loaded inode even after pathname replacement. */
        if (snprintf(path, sizeof(path), "%s/%s/exe", root, entry->d_name) >= (int)sizeof(path)
            || !c300x_sha256_file_hex(path, digest, sizeof(digest))
            || strcmp(digest, C300X_MEDIA_TEARDOWN_PATCHED_SHA256) != 0) {
            valid = 0;
            break;
        }
        found = 1;
    }
    closedir(directory);
    return valid && found;
}
