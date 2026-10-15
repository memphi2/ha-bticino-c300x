#include "../src/https_client.h"

#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    char response[128];
    const char *error = NULL;
    long status = 0;
    if (argc != 3) {
        return 2;
    }
    int available = c300x_https_available();
    int ok = c300x_https_post(
        argv[1], "X-Test-Token", "test-token", "{\"test\":true}",
        response, sizeof(response), atoi(argv[2]), &status, &error
    );
    printf("available=%d ok=%d status=%ld error=%s\n", available, ok, status, error ? error : "none");
    if (ok) {
        puts(response);
    }
    return 0;
}
