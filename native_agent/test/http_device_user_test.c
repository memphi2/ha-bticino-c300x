/* Real route/job ownership, with all device file operations replaced locally. */
#include "../src/http_device_user.h"
#include "../src/device_user.h"
#include "../src/device_routing.h"
#include "../src/string_util.h"

#include <assert.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static const char *test_case;
static int response_status, responses, closes, writes, applied, ensured, restored, reads;
static char response_body[8192], write_reason[96];
static long long time_offset;
static volatile sig_atomic_t shutdown_requested;

static void shutdown_signal(int signo)
{
    (void)signo;
    shutdown_requested = 1;
}

long long c300x_monotonic_ms(void)
{
    struct timespec now;
    assert(clock_gettime(CLOCK_MONOTONIC, &now) == 0);
    return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000 + time_offset;
}

void c300x_http_send_json(int fd, int status, const char *reason, const char *body)
{
    assert(fd == 1234 && reason != NULL);
    response_status = status;
    responses++;
    c300x_copy_string(response_body, sizeof(response_body), body);
}

void close_agent_socket(int fd)
{
    assert(fd == 1234);
    closes++;
}

static void record_write(void *context, const char *kind, const char *reason)
{
    assert(context == &writes && strcmp(kind, "device_user") == 0);
    writes++;
    c300x_copy_string(write_reason, sizeof(write_reason), reason);
}

int c300x_device_user_read_status(struct c300x_device_user_status *status)
{
    reads++;
    memset(status, 0, sizeof(*status));
    status->status_available = 1;
    status->supported = 1;
    c300x_copy_string(status->account_label, sizeof(status->account_label), "A \"quoted\" label");
    return 1;
}

int c300x_device_routing_read_status(struct c300x_device_routing_status *status)
{
    memset(status, 0, sizeof(*status));
    c300x_copy_string(status->state, sizeof(status->state), "stock");
    return 1;
}

int c300x_device_routing_apply(struct c300x_device_routing_status *status, char *error, size_t size)
{
    (void)status;
    assert(!ensured && !restored);
    applied++;
    c300x_copy_string(error, size, "routing detail");
    return strcmp(test_case, "routing-failure") != 0;
}

int c300x_device_user_ensure_homeassistant(struct c300x_device_user_status *status,
    const char *label, char *error, size_t size)
{
    (void)status;
    assert(applied == 1 && strlen(label) <= C300X_DEVICE_USER_LABEL_LEN - 1);
    ensured++;
    c300x_copy_string(error, size, "user detail");
    return strcmp(test_case, "user-failure") != 0;
}

int c300x_device_routing_restore(struct c300x_device_routing_status *status, char *error, size_t size)
{
    (void)status;
    restored++;
    c300x_copy_string(error, size, "restore detail");
    return strcmp(test_case, "restore-failure") != 0;
}

int main(int argc, char **argv)
{
    struct c300x_http_maintenance owner;
    struct c300x_config *config = calloc(1, sizeof(*config));
    struct request *request = calloc(1, sizeof(*request));
    struct pollfd fd;
    assert(argc == 4 && config != NULL && request != NULL);
    test_case = argv[1];
    int transaction_test = strcmp(test_case, "transaction") == 0;
    if (transaction_test) {
        struct sigaction action = {0};
        action.sa_handler = shutdown_signal;
        assert(sigemptyset(&action.sa_mask) == 0);
        /* No SA_RESTART: exercise EINTR in both capture reads and child reap. */
        assert(sigaction(SIGTERM, &action, NULL) == 0);
    }
    const char *operation = argv[3];
    config->maintenance_enabled = 1;
    config->api_no_auth = 1;
    config->maintenance_no_auth_allowed = 1;
    c300x_copy_string(config->maintenance_qml_patch_script,
        sizeof(config->maintenance_qml_patch_script), argv[2]);
    c300x_copy_string(request->method, sizeof(request->method), "POST");
    if (strcmp(operation, "status") == 0) {
        c300x_copy_string(request->method, sizeof(request->method), "GET");
        c300x_copy_string(request->path, sizeof(request->path), "/api/v1/device-user");
    } else if (strcmp(operation, "restore") == 0) {
        c300x_copy_string(request->path, sizeof(request->path),
            "/api/v1/maintenance/device-user/actions/restore-homeassistant-setup");
        c300x_copy_string(request->body, sizeof(request->body), "{\"confirm\":\"restore_ha_user_setup\"}");
    } else {
        c300x_copy_string(request->path, sizeof(request->path),
            "/api/v1/maintenance/device-user/actions/ensure-homeassistant");
        c300x_copy_string(request->body, sizeof(request->body),
            "{\"confirm\":\"ensure_homeassistant_user\",\"account_label\":\"My label\"}");
    }
    if (strcmp(test_case, "unauthorized") == 0) {
        config->maintenance_no_auth_allowed = 0;
    }
    if (strcmp(test_case, "unconfirmed") == 0) {
        request->body[0] = '\0';
    }
    c300x_http_maintenance_init(&owner, record_write, &writes);
    assert(c300x_http_maintenance_prepare(&owner, &fd) == -1 && fd.fd == -1);
    assert(c300x_http_device_user_route(&owner, 1234, config, request));
    if (transaction_test) {
        /* Mirror HTTP shutdown: finish dispatch, then close the job owner.
         * The pre-fix route returns early and kills its still-writing child. */
        while (!shutdown_requested) {
            c300x_http_maintenance_tick(&owner);
            (void)poll(NULL, 0, 10);
        }
        c300x_http_maintenance_close(&owner);
        assert(owner.context == NULL && !c300x_http_maintenance_busy(&owner));
        while (waitpid(-1, NULL, 0) > 0 || errno == EINTR) {}
        assert(errno == ECHILD);
        printf("{\"writes\":%d,\"restored\":%d,\"status\":%d}\n", writes, restored, response_status);
        free(request);
        free(config);
        return 0;
    }
    int asynchronous = c300x_http_maintenance_busy(&owner);
    if (asynchronous) {
        assert(responses == 0 && owner.client_fd == 1234);
        assert(owner.job.capture_size == 4096);
        long long remaining = owner.job.deadline_ms - c300x_monotonic_ms();
        assert(remaining > 9000 && remaining <= 10000);
    }
    if (strcmp(test_case, "shutdown") == 0) {
        pid_t child = owner.job.pid;
        assert(child > 0);
        c300x_http_maintenance_close(&owner);
        assert(owner.client_fd == -1 && owner.context == NULL && closes == 1);
        assert(!c300x_http_maintenance_busy(&owner));
        c300x_http_maintenance_close(&owner);
        c300x_http_maintenance_tick(&owner);
        assert(closes == 1);
        int status;
        pid_t reaped = waitpid(child, &status, 0);
        assert(reaped == child || (reaped < 0 && errno == ECHILD));
        assert(responses == 0 && writes == 0);
        free(request);
        free(config);
        return 0;
    }
    if (strcmp(test_case, "timeout") == 0) {
        time_offset = 10001;
    }
    long long deadline = c300x_monotonic_ms() + 3000;
    while (c300x_http_maintenance_busy(&owner)) {
        assert(c300x_monotonic_ms() < deadline);
        int timeout = c300x_http_maintenance_prepare(&owner, &fd);
        assert(timeout >= 0 && timeout <= 50);
        (void)poll(&fd, 1, timeout);
        c300x_http_maintenance_tick(&owner);
    }
    assert(responses == 1 && closes == asynchronous && owner.context == NULL);
    assert(c300x_http_maintenance_prepare(&owner, &fd) == -1 && fd.fd == -1);
    if (strcmp(test_case, "report") == 0) {
        printf("{\"status\":%d,\"writes\":%d,\"restored\":%d,\"body\":%s}\n",
            response_status, writes, restored, response_body);
    } else if (strcmp(test_case, "unauthorized") == 0 || strcmp(test_case, "unconfirmed") == 0) {
        assert(response_status == (strcmp(test_case, "unauthorized") == 0 ? 403 : 400));
        assert(!applied && !ensured && !restored && !reads && !writes);
    } else if (strcmp(operation, "status") == 0) {
        assert(response_status == 200 && writes == 0 && reads == 1);
        assert(strstr(response_body, "\"status_available\":true") != NULL);
        assert(strstr(response_body, "\"account_label\":\"A \\\"quoted\\\" label\"") != NULL);
    } else if (strcmp(test_case, "success") == 0 || strcmp(test_case, "overflow") == 0
        || (strcmp(test_case, "missing") == 0 && strcmp(operation, "restore") == 0)) {
        assert(response_status == 200 && writes == 1
            && reads == (strcmp(operation, "ensure") == 0 ? 2 : 1));
        assert(strcmp(write_reason, strcmp(operation, "restore") == 0
            ? "restore_homeassistant_media_user_setup" : "ensure_homeassistant_user") == 0);
        assert(restored == (strcmp(operation, "restore") == 0));
    } else {
        const char *error = strcmp(test_case, "routing-failure") == 0 ? "device_routing_failed"
            : strcmp(test_case, "user-failure") == 0 ? "device_user_update_failed"
            : strcmp(test_case, "restore-failure") == 0 ? "device_routing_restore_failed"
            : strcmp(operation, "restore") == 0 ? "media_user_label_restore_failed"
            : "media_user_label_setup_failed";
        assert(response_status == 500 && writes == 0 && strstr(response_body, error) != NULL);
    }
    c300x_http_maintenance_close(&owner);
    assert(closes == asynchronous);
    free(request);
    free(config);
    return 0;
}
