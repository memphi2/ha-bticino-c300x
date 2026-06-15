#include "c300x_agent.h"

#include <signal.h>
#include <stdio.h>
#include <string.h>

static void print_usage(const char *program)
{
    fprintf(
        stderr,
        "Usage: %s [--config PATH] [--check-config] [--version]\n",
        program
    );
}

int main(int argc, char **argv)
{
    const char *config_path = "config.json";
    int check_config = 0;
    struct c300x_config config;
    char error[256] = {0};

    for (int index = 1; index < argc; index++) {
        if (strcmp(argv[index], "--config") == 0) {
            if (index + 1 >= argc) {
                print_usage(argv[0]);
                return 2;
            }
            config_path = argv[++index];
        } else if (strcmp(argv[index], "--check-config") == 0) {
            check_config = 1;
        } else if (strcmp(argv[index], "--version") == 0) {
            printf("%s\n", C300X_NATIVE_AGENT_VERSION);
            return 0;
        } else {
            print_usage(argv[0]);
            return 2;
        }
    }

    if (!c300x_load_config(config_path, &config, error, sizeof(error))) {
        fprintf(stderr, "config error: %s\n", error);
        return 2;
    }

    if (check_config) {
        printf("config ok\n");
        return 0;
    }

    (void)signal(SIGPIPE, SIG_IGN);
    return c300x_run(&config);
}
