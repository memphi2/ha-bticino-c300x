#include "device_file.h"

#include "c300x_agent.h"

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int c300x_device_file_mkdir_p(const char *path) {
    char tmp[C300X_MAX_PATH_LEN];
    size_t len = strlen(path);
    char *p;
    if (len == 0 || len >= sizeof(tmp)) {
        return 0;
    }
    memcpy(tmp, path, len + 1);
    for (p = tmp + 1; *p != '\0'; p++) {
        if (*p == '/') {
            *p = '\0';
            if (mkdir(tmp, 0755) != 0 && errno != EEXIST) {
                return 0;
            }
            *p = '/';
        }
    }
    return mkdir(tmp, 0755) == 0 || errno == EEXIST;
}

/* Persist directory entries as well as file data, including newly created
 * backup ancestors. This runs only around explicit maintenance writes. */
int c300x_device_file_sync_parents(const char *path)
{
    char *parent = strdup(path);
    if (parent == NULL) return 0;
    char *slash = strrchr(parent, '/');
    if (slash != NULL) slash[slash == parent ? 1 : 0] = '\0';
    int ok = 1;
    for (;;) {
        int fd = open(slash == NULL ? "." : parent, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
        if (fd < 0) { ok = 0; break; }
        ok = fsync(fd) == 0;
        close(fd);
        if (!ok || slash == NULL || strcmp(parent, "/") == 0) break;
        slash = strrchr(parent, '/');
        if (slash == NULL) break;
        slash[slash == parent ? 1 : 0] = '\0';
    }
    free(parent);
    return ok;
}
