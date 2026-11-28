#include "foreign_services.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

#define SSH_PORT 22U
#define TCP_LISTEN 0x0AU
/* A station has a few dozen sockets; stop reading a runaway table. */
#define MAX_SOCKET_LINES 4096

/* davemajor/c300x-root and daniel-sc/bticino-c100x-firmware-tools run their
 * own dropbear with its own pidfile; the MQTT extras of fquinto and
 * jorgeavlobo install a watchdog that restarts the factory dropbear. */
static const char *const ssh_managers[] = {"c300x-ssh", "c100x-ssh", "bt_service_watchdog"};

const char *c300x_ssh_foreign_manager(void)
{
    char path[128];
    for (size_t index = 0; index < sizeof(ssh_managers) / sizeof(ssh_managers[0]); index++) {
        if (snprintf(path, sizeof(path), "%s/etc/init.d/%s", C300X_FOREIGN_ROOT, ssh_managers[index])
                < (int)sizeof(path)
            && access(path, F_OK) == 0) {
            return ssh_managers[index];
        }
    }
    return NULL;
}

static int table_listens(const char *name)
{
    char path[128], line[256];
    unsigned int port, state;
    int whole = 1, found = 0;
    FILE *file;
    if (snprintf(path, sizeof(path), "%s/%s", C300X_PROC_NET_DIR, name) >= (int)sizeof(path)
        || (file = fopen(path, "re")) == NULL) {
        return 0;
    }
    for (int lines = 0; !found && lines < MAX_SOCKET_LINES && fgets(line, sizeof(line), file); lines++) {
        /* Only the start of a line holds the fields; skip the rest of a long one. */
        int start = whole;
        whole = strchr(line, '\n') != NULL;
        found = start && sscanf(line, " %*u: %*[0-9A-Fa-f]:%x %*[0-9A-Fa-f]:%*x %x", &port, &state) == 2
            && port == SSH_PORT && state == TCP_LISTEN;
    }
    fclose(file);
    return found;
}

int c300x_ssh_port_listening(void)
{
    return table_listens("tcp") || table_listens("tcp6");
}
