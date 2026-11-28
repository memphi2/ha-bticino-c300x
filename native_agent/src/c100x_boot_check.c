#include "c100x_boot_check.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define C100X_DEFAULT_BACKUP_DIR "/home/bticino/cfg/extra/c300x-device-file-backups/c100x-display"

const char *c100x_boot_check(void)
{
    const char *dir = getenv("C100X_BACKUP_DIR");
    char path[512], line[32] = "";
    FILE *file;

    if (dir == NULL || dir[0] == '\0') {
        dir = C100X_DEFAULT_BACKUP_DIR;
    }
    if (snprintf(path, sizeof(path), "%s/boot-check-failed", dir) >= (int)sizeof(path)
        || (file = fopen(path, "r")) == NULL) {
        return "";
    }
    if (fgets(line, sizeof(line), file) == NULL) {
        line[0] = '\0';
    }
    fclose(file);
    /* Any other content still is a failed check. */
    return !strcmp(line, "payload_unavailable\n") ? "payload_unavailable" : "boot_check_failed";
}
