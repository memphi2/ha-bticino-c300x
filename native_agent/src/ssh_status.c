#include "ssh_status.h"
#include "foreign_services.h"
#include "http_util.h"

#include <stdio.h>

int c300x_ssh_send_status(int fd, int factory, int require)
{
    char body[224], manager_json[40] = "null";
    const char *manager = c300x_ssh_foreign_manager();
    int listening = c300x_ssh_port_listening();
    /* SSH answers, but the factory dropbear is not it, or a tool restarts it. */
    int external = listening && (manager != NULL || factory == 0);
    int running = listening || factory == 1;
    if (require >= 0 && running != require) {
        return 0;
    }
    if (external || manager != NULL) {
        /* Names come from a fixed table and need no escaping. */
        snprintf(manager_json, sizeof(manager_json), "\"%s\"", manager != NULL ? manager : "unknown");
    }
    snprintf(body, sizeof(body),
        "{\"ok\":true,\"enabled\":%s,\"running\":%s,\"state\":\"%s\",\"listening\":%s,"
        "\"factory_running\":%s,\"manager\":%s}\n",
        running ? "true" : "false", running ? "true" : "false",
        external ? "managed_externally" : running ? "running" : "stopped",
        listening ? "true" : "false",
        factory < 0 ? "null" : factory ? "true" : "false", manager_json);
    c300x_http_send_json(fd, 200, "OK", body);
    return 1;
}

int c300x_ssh_refuse_managed(int fd)
{
    char body[128];
    const char *manager = c300x_ssh_foreign_manager();
    if (manager == NULL || !c300x_ssh_port_listening()) {
        return 0;
    }
    snprintf(body, sizeof(body), "{\"ok\":false,\"error\":\"ssh_managed_externally\",\"manager\":\"%s\"}\n",
        manager);
    c300x_http_send_json(fd, 409, "Conflict", body);
    return 1;
}
