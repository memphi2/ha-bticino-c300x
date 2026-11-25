#include "../src/display_touch.h"

#if defined(TEST_TERM_IN_WINDOW) || defined(TEST_LOG_REMOUNTS)
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/statvfs.h>

int __wrap_statvfs(const char *path, struct statvfs *info)
{
    (void)path;
    memset(info, 0, sizeof(*info));
    info->f_flag = ST_RDONLY;
    return 0;
}

/* Every remount is logged; with TEST_TERM_IN_WINDOW the job is also
 * stopped right after / went writable. */
int __wrap_system(const char *command)
{
    fprintf(stderr, "%s\n", command);
#ifdef TEST_TERM_IN_WINDOW
    if (strstr(command, "remount,rw") != NULL) {
        raise(SIGTERM);
    }
#endif
    return 0;
}
#endif

int main(int argc, char **argv)
{
    return argc == 2 ? c300x_display_touch_cli(argv[1]) : 2;
}
