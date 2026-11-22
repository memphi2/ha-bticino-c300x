#include "../src/http_service_commands.h"

#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int replies, destroys, schedules, closes, expect_ok;

long long c300x_monotonic_ms(void)
{
    struct timespec now;
    assert(clock_gettime(CLOCK_MONOTONIC, &now) == 0);
    return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

void c300x_http_send_json(int fd, int status, const char *reason, const char *body)
{
    (void)fd; (void)status; (void)reason; (void)body;
    assert(0 && "custom reboot completion must not send a service error");
}

void close_agent_socket(int fd)
{
    assert(fd == 1234);
    closes++;
}

static int schedule(const char *program, const char *argument, int delay)
{
    assert(strcmp(program, "/sbin/reboot") == 0 && argument == NULL && delay == 500);
    schedules++;
    return expect_ok;
}

static void reply(int fd, int ok, void *context)
{
    assert(fd == 1234 && context != NULL && ok == expect_ok && destroys == 0);
    replies++;
}

static void destroy(void *context)
{
    assert(context != NULL);
    destroys++;
    free(context);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    int cancel = strcmp(argv[1], "cancel") == 0;
    int async = strcmp(argv[1], "immediate-failure") != 0;
    expect_ok = strcmp(argv[1], "success") == 0;
    struct c300x_config *config = calloc(1, sizeof(*config));
    struct c300x_http_maintenance owner;
    assert(config != NULL);
    config->maintenance_ssh_start_enabled = async;
    config->maintenance_reboot_delay_ms = 500;
    c300x_http_maintenance_init(&owner, NULL, NULL);
    void *context = malloc(1);
    assert(context != NULL);
    c300x_http_service_reboot(&owner, 1234, config, schedule, reply, context, destroy);
    if (async) {
        assert(c300x_http_maintenance_busy(&owner) && !schedules && !destroys);
    }
    if (!cancel) {
        for (int i = 0; c300x_http_maintenance_busy(&owner) && i < 100; i++) {
            struct pollfd fd;
            int timeout = c300x_http_maintenance_prepare(&owner, &fd);
            (void)poll(&fd, 1, timeout);
            c300x_http_maintenance_tick(&owner);
        }
        assert(!c300x_http_maintenance_busy(&owner));
        assert(replies == 1 && schedules == 1 && destroys == 1);
    }
    c300x_http_maintenance_close(&owner);
    assert(destroys == 1 && closes == async);
    assert(owner.context == NULL && owner.complete == NULL);
    if (cancel) {
        assert(!replies && !schedules);
    }
    free(config);
    return 0;
}
