/* A write script without a deadline runs to its end; one with a deadline is
 * still stopped. argv: script, marker file the script writes when it ends. */
#include <assert.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>

#include "../src/command_job.h"

void set_fd_nonblocking(int fd)
{
    int flags = fcntl(fd, F_GETFL, 0);
    assert(flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0);
}

long long c300x_monotonic_ms(void)
{
    return 0;
}

int main(int argc, char **argv)
{
    char out[64];
    int exit_code = -1;
    assert(argc == 3);

    assert(!c300x_command_capture(argv[1], "slow", out, sizeof(out), 100, &exit_code));
    assert(access(argv[2], F_OK) != 0);

    assert(c300x_command_capture(argv[1], "slow", out, sizeof(out),
        C300X_COMMAND_NO_DEADLINE, &exit_code));
    assert(exit_code == 0);
    assert(strcmp(out, "done\n") == 0);
    assert(access(argv[2], F_OK) == 0);

    assert(!c300x_command_capture(argv[1], "fail", out, sizeof(out),
        C300X_COMMAND_NO_DEADLINE, &exit_code));
    assert(exit_code == 3);
    return 0;
}
