#include "device_file.h"

#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

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
