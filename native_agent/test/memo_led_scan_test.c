#include "../src/memo_led_scan.h"
#include <assert.h>
#include <poll.h>
#include <stdio.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    assert(argc == 3);
    int done, watch;
    struct memo_scan *scan = memo_scan_start(argv[1], argv[2], &done);
    assert(scan);
    struct pollfd p = {.fd = done, .events = POLLIN};
    assert(poll(&p, 1, 2000) == 1);
    printf("%d\n", memo_scan_finish(scan, &watch));
    close(watch);
    return 0;
}
