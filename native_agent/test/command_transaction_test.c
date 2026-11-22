#include "../src/command_transaction.h"

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>

static volatile sig_atomic_t signals;

static void note_shutdown(int signo)
{
    (void)signo;
    signals++;
}

static int descriptor_count(void)
{
    int count = 0;
    for (int fd = 0; fd < 512; fd++) {
        count += fcntl(fd, F_GETFD) >= 0;
    }
    return count;
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    size_t capacity = (size_t)atoi(argv[2]);
    char output[32];
    assert(capacity > 0 && capacity <= sizeof(output));
    struct sigaction action = {0};
    action.sa_handler = note_shutdown;
    assert(sigemptyset(&action.sa_mask) == 0);
    assert(sigaction(SIGTERM, &action, NULL) == 0);
    int descriptors = descriptor_count();
    assert(!c300x_command_transaction_capture(NULL, "test", output, capacity));
    assert(!c300x_command_transaction_capture(argv[1], "test", NULL, capacity));
    assert(!c300x_command_transaction_capture(argv[1], "test", output, 0));
    int ok = c300x_command_transaction_capture(argv[1], "test", output, capacity);
    assert(descriptor_count() == descriptors);
    assert(waitpid(-1, NULL, WNOHANG) == -1 && errno == ECHILD);
    printf("{\"ok\":%d,\"length\":%zu,\"signals\":%d,\"prefix\":\"%s\"}\n",
        ok, strlen(output), signals, output);
    return 0;
}
