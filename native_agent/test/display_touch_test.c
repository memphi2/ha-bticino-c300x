#include "../src/display_touch.h"

#ifdef TEST_TERM_IN_WINDOW
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

/* The job is stopped right after / went writable. */
int __wrap_system(const char *command)
{
    fprintf(stderr, "%s\n", command);
    if (strstr(command, "remount,rw") != NULL) {
        raise(SIGTERM);
    }
    return 0;
}
#endif

int main(int argc, char **argv)
{
    return argc == 2 ? c300x_display_touch_cli(argv[1]) : 2;
}
