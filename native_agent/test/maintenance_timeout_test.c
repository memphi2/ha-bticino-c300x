#include "../src/http_maintenance.h"
#include "../src/qml_recovery.h"
#include "../src/string_util.h"

#include <assert.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* Real time plus a jump, so a deadline passes without waiting for it. */
static long long offset_ms;
long long c300x_monotonic_ms(void)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000 + offset_ms;
}

static int responses, response_status;
static char response_body[512];
void c300x_http_send_json(int fd, int status, const char *reason, const char *body)
{
    (void)fd; (void)reason;
    responses++;
    response_status = status;
    snprintf(response_body, sizeof(response_body), "%s", body);
}

void close_agent_socket(int fd) { (void)fd; }

/* Mode "reload-qt5" stands for the Qt 5 display of firmware 3.0.x. */
static const char *test_mode = "";
int c300x_device_display_is_qt5(void) { return strcmp(test_mode, "reload-qt5") == 0; }

static int writes;
static void record_write(void *context, const char *kind, const char *reason)
{
    (void)context; (void)kind; (void)reason;
    writes++;
}

static int zombie(pid_t pid)
{
    char path[64], stat[256];
    snprintf(path, sizeof(path), "/proc/%d/stat", (int)pid);
    FILE *file = fopen(path, "r");
    size_t size = file != NULL ? fread(stat, 1, sizeof(stat) - 1, file) : 0;
    if (file != NULL) {
        fclose(file);
    }
    stat[size] = '\0';
    char *state = strrchr(stat, ')');
    return state != NULL && state[1] == ' ' && state[2] == 'Z';
}

static int lines(const char *path)
{
    FILE *file = fopen(path, "r");
    int count = 0, c;
    while (file != NULL && (c = fgetc(file)) != EOF) {
        count += c == '\n';
    }
    if (file != NULL) {
        fclose(file);
    }
    return count;
}

static void run_for(struct c300x_http_maintenance *owner, int real_ms, int (*done)(void))
{
    struct timespec start, now;
    clock_gettime(CLOCK_MONOTONIC, &start);
    for (;;) {
        struct pollfd fd;
        int timeout = c300x_http_maintenance_prepare(owner, &fd);
        if (timeout >= 0) {
            (void)poll(fd.fd >= 0 ? &fd : NULL, fd.fd >= 0 ? 1 : 0, timeout > 20 ? 20 : timeout);
        }
        c300x_http_maintenance_tick(owner);
        clock_gettime(CLOCK_MONOTONIC, &now);
        if ((done != NULL && done())
            || (now.tv_sec - start.tv_sec) * 1000 + (now.tv_nsec - start.tv_nsec) / 1000000 >= real_ms) {
            return;
        }
    }
}

static int answered(void) { return responses > 0; }
static struct c300x_http_maintenance *watched;
static int idle(void) { return !c300x_http_maintenance_busy(watched); }
static int started(void) { return access("started", F_OK) == 0; }

int main(int argc, char **argv)
{
    assert(argc == 3);
    const char *mode = argv[2];
    test_mode = mode;
    struct c300x_config *config = calloc(1, sizeof(*config));
    struct request *request = calloc(1, sizeof(*request));
    struct c300x_http_maintenance owner;
    assert(config != NULL && request != NULL);
    config->maintenance_enabled = config->api_no_auth = config->maintenance_no_auth_allowed = 1;
    config->maintenance_qml_patch_enabled = 1;
    c300x_copy_string(config->maintenance_qml_patch_script, sizeof(config->maintenance_qml_patch_script), argv[1]);
    config->maintenance_gui_reload_enabled = 1;
    c300x_copy_string(config->maintenance_gui_reload_script, sizeof(config->maintenance_gui_reload_script), argv[1]);
    if (strcmp(mode, "status") == 0) {
        c300x_copy_string(request->method, sizeof(request->method), "GET");
        c300x_copy_string(request->path, sizeof(request->path), "/api/v1/maintenance/qml-patch");
    } else if (strncmp(mode, "reload", 6) == 0) {
        c300x_copy_string(request->method, sizeof(request->method), "POST");
        c300x_copy_string(request->path, sizeof(request->path), "/api/v1/maintenance/gui/actions/reload");
        c300x_copy_string(request->body, sizeof(request->body), "{\"confirm\":\"reload_gui\"}");
    } else {
        c300x_copy_string(request->method, sizeof(request->method), "POST");
        c300x_copy_string(request->path, sizeof(request->path), "/api/v1/maintenance/qml-patch/actions/apply");
        c300x_copy_string(request->body, sizeof(request->body), "{\"confirm\":\"apply_qml_patch\"}");
    }
    c300x_http_maintenance_init(&owner, record_write, NULL);
    if (strncmp(mode, "reload-", 7) == 0) {
        /* A GUI reload: 10 s on Qt 4 as in 2.9.2, the write limit on Qt 5. */
        int qt5 = strcmp(mode, "reload-qt5") == 0;
        config->maintenance_gui_reload_enabled = 1;
        c300x_copy_string(config->maintenance_gui_reload_script,
            sizeof(config->maintenance_gui_reload_script), argv[1]);
        c300x_copy_string(request->path, sizeof(request->path), "/api/v1/maintenance/gui/actions/reload");
        c300x_copy_string(request->body, sizeof(request->body), "{\"confirm\":\"reload_gui\"}");
        long long before = c300x_monotonic_ms();
        assert(c300x_http_maintenance_route(&owner, 1234, config, request));
        long long limit = owner.job.deadline_ms - before;
        assert(owner.job.pid > 0 && responses == 0 && owner.gui_reload && !owner.records_write);
        assert(qt5 ? limit >= C300X_QML_WRITE_TIMEOUT_MS && limit < C300X_QML_WRITE_TIMEOUT_MS + 1000
                   : limit >= 10000 && limit < 11000);
        assert(owner.job.term_grace_ms == 0);
        c300x_http_maintenance_close(&owner);
        free(request);
        free(config);
        return 0;
    }
    if (strcmp(mode, "recover") == 0) {
        /* Agent start: a write-class job without a client holds the slot. */
        c300x_qml_recovery_start(&owner, config);
        pid_t child = owner.job.pid;
        assert(child > 0 && c300x_http_maintenance_busy(&owner));
        run_for(&owner, 5000, started);
        assert(c300x_http_maintenance_route(&owner, 1234, config, request));
        assert(responses == 1 && response_status == 409);
        offset_ms += 30001;
        run_for(&owner, 100, NULL);
        assert(owner.job.pid == child && kill(child, 0) == 0 && c300x_http_maintenance_busy(&owner));
        watched = &owner;
        run_for(&owner, 5000, idle);
        assert(access("rolled", F_OK) == 0 && !c300x_http_maintenance_busy(&owner));
        assert(responses == 1 && writes == 0);
        c300x_http_maintenance_close(&owner);
        free(request);
        free(config);
        return 0;
    }
    assert(c300x_http_maintenance_route(&owner, 1234, config, request));
    pid_t child = owner.job.pid;
    assert(child > 0 && responses == 0);
    run_for(&owner, 5000, started);
    assert(started() && responses == 0);

    if (strcmp(mode, "deadline-exit") == 0) {
        /* Ended by itself, but reaped only on the deadline tick: its answer. */
        FILE *finish = fopen("finish", "w");
        assert(finish != NULL);
        fclose(finish);
        for (int waited = 0; !zombie(child); waited++) {
            assert(waited < 500);
            usleep(10000);
        }
        offset_ms += 30001;
        run_for(&owner, 1000, answered);
        assert(responses == 1 && response_status == 200 && writes == 1);
        assert(strstr(response_body, "\"changed_files\":1") != NULL);
    } else if (strcmp(mode, "exit131") == 0) {
        /* A failed write before its deadline is no timeout. */
        FILE *finish = fopen("finish", "w");
        assert(finish != NULL);
        fclose(finish);
        run_for(&owner, 5000, answered);
        assert(responses == 1 && response_status == 502);
        assert(strstr(response_body, "\"state\":\"script_failed\"") != NULL);
    } else if (strcmp(mode, "overflow") == 0) {
        /* Too much output fails the write; it still gets its rollback. */
        FILE *finish = fopen("finish", "w");
        assert(finish != NULL);
        fclose(finish);
        run_for(&owner, 5000, answered);
        assert(responses == 1 && response_status == 502 && access("rolled", F_OK) == 0);
        assert(strstr(response_body, "\"state\":\"script_failed\"") != NULL);
        assert(kill(child, 0) == -1 && errno == ESRCH);
    } else if (strcmp(mode, "shutdown-grace") == 0) {
        /* Shutdown while the deadline's grace period runs: no second SIGTERM. */
        offset_ms += 30001;
        run_for(&owner, 100, NULL);
        assert(responses == 0 && kill(child, 0) == 0);
        c300x_http_maintenance_close(&owner);
        assert(access("rolled", F_OK) == 0 && lines("terms") == 1);
        assert(kill(child, 0) == -1 && errno == ESRCH);
    } else if (strcmp(mode, "shutdown") == 0) {
        /* Shutdown during a write: the rollback trap runs to its end. */
        c300x_http_maintenance_close(&owner);
        assert(access("rolled", F_OK) == 0);
        assert(kill(child, 0) == -1 && errno == ESRCH);
        assert(responses == 0 && !c300x_http_maintenance_busy(&owner));
    } else if (strncmp(mode, "reload", 6) == 0) {
        /* A GUI restart past its 10 seconds: SIGTERM, the trap finishes the
         * restart, and only then the unchanged answer. */
        offset_ms += 10001;
        run_for(&owner, 100, NULL);
        assert(responses == 0 && owner.job.pid == child && kill(child, 0) == 0);
        if (strcmp(mode, "reload-ignore") == 0) {
            offset_ms += 15001;
        }
        run_for(&owner, 5000, answered);
        assert(responses == 1 && response_status == 502 && writes == 0);
        assert(strstr(response_body, "\"error\":\"reload_failed\"") != NULL);
        if (strcmp(mode, "reload") == 0) {
            assert(access("rolled", F_OK) == 0 && lines("terms") == 1);
        }
        assert(kill(child, 0) == -1 && errno == ESRCH);
        assert(!c300x_http_maintenance_busy(&owner));
    } else if (strcmp(mode, "status") == 0) {
        /* No grace for a read: killed at its deadline, answered at once. */
        offset_ms += 10001;
        run_for(&owner, 1000, answered);
        assert(responses == 1 && response_status == 502);
        assert(strstr(response_body, "\"state\":\"script_failed\"") != NULL);
    } else {
        offset_ms += 30001;
        run_for(&owner, 100, NULL);
        /* SIGTERM, then the HTTP client keeps waiting for the script. */
        assert(responses == 0 && owner.job.pid == child && kill(child, 0) == 0);
        if (strcmp(mode, "ignore") == 0) {
            offset_ms += 15001;
        }
        run_for(&owner, 5000, answered);
        assert(responses == 1 && response_status == 504);
        assert(strstr(response_body, "\"error\":\"qml_patch_timeout\"") != NULL);
        if (strcmp(mode, "rollback") == 0) {
            assert(access("rolled", F_OK) == 0 && lines("terms") == 1);
            assert(strstr(response_body, "\"rolled_back\":true") != NULL);
        } else {
            assert(strstr(response_body, "\"rolled_back\":false") != NULL);
        }
        assert(kill(child, 0) == -1 && errno == ESRCH);
        assert(!c300x_http_maintenance_busy(&owner));
    }
    c300x_http_maintenance_close(&owner);
    free(request);
    free(config);
    return 0;
}
