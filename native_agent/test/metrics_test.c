#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static unsigned long long test_busy = 1000;
static unsigned long long test_idle = 99000;
static long long test_now_ms = 100000;
static unsigned test_proc_reads;
static unsigned test_temperature_reads;
static unsigned test_random_reads;

static int metrics_clock_gettime(clockid_t clock_id, struct timespec *now)
{
    (void)clock_id;
    now->tv_sec = test_now_ms / 1000;
    now->tv_nsec = (test_now_ms % 1000) * 1000000;
    return 0;
}

static FILE *metrics_fopen(const char *path, const char *mode)
{
    assert(strcmp(mode, "r") == 0 || strcmp(mode, "rb") == 0);
    static char cpu[256];
    static char load[] = "0.01 0.01 0.01 1/100 100\n";
    static char memory[] = "MemTotal: 100000 kB\nMemAvailable: 80000 kB\n";
    if (strcmp(path, "/proc/stat") == 0) {
        test_proc_reads++;
        snprintf(cpu, sizeof(cpu), "cpu %llu 0 0 %llu 0 0 0 0\n", test_busy, test_idle);
        return fmemopen(cpu, strlen(cpu), "r");
    }
    if (strcmp(path, "/proc/loadavg") == 0) {
        test_proc_reads++;
        return fmemopen(load, strlen(load), "r");
    }
    if (strcmp(path, "/proc/meminfo") == 0) {
        test_proc_reads++;
        return fmemopen(memory, strlen(memory), "r");
    }
    if (strncmp(path, "/sys/", 5) == 0) {
        test_temperature_reads++;
        return NULL;
    }
    assert(strcmp(path, "/dev/urandom") == 0);
    test_random_reads++;
    return fopen(path, mode);
}

#define fopen metrics_fopen
#define clock_gettime metrics_clock_gettime
#include "../src/system_metrics.c"
#undef clock_gettime
#undef fopen
#include "../src/http.c"

static void baseline(struct c300x_config *config, struct agent_runtime *runtime, time_t now, double percent)
{
    memset(runtime, 0, sizeof(*runtime));
    runtime->config = config;
    runtime->subscription_count = 1;
    runtime->subscriptions[0].event_count = 1;
    strcpy(runtime->subscriptions[0].events[0], "system.metrics_changed");
    runtime->network_online = 1;
    runtime->network_checked_at = time(NULL);
    test_busy = 1000;
    test_idle = 99000;
    c300x_system_metrics_monitor_init(config, &runtime->metrics);
    runtime->metrics.last.has_cpu_usage = 1;
    runtime->metrics.last.cpu_usage_percent = percent;
    runtime->metrics.next_sample_ms = test_now_ms + 30000;
    c300x_system_metrics_monitor_delivered(&runtime->metrics, now);
}

static void check_http_snapshot(struct c300x_config *config, struct agent_runtime *runtime, time_t now)
{
    int pair[2];
    char response[8192];
    baseline(config, runtime, now, 1.0);
    test_busy += 2;
    test_idle += 8;
    unsigned reads_before = test_proc_reads + test_temperature_reads + test_random_reads;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    handle_system_metrics(pair[0], runtime);
    close(pair[0]);
    ssize_t received = recv(pair[1], response, sizeof(response) - 1, 0);
    assert(received > 0);
    response[received] = '\0';
    close(pair[1]);
    assert(strstr(response, "\"cpu_usage_percent\":1.0") != NULL);
    assert(runtime->metrics.last_delivered.cpu_usage_percent == 1.0);
    assert(test_proc_reads + test_temperature_reads + test_random_reads == reads_before);
}

static void check_failed_push(struct c300x_config *config, struct agent_runtime *runtime, time_t now)
{
    baseline(config, runtime, now, 15.0);
    /* Invalid callback fails deterministically without accessing a network. */
    strcpy(runtime->subscriptions[0].callback_url, "invalid");
    test_busy += 30;
    test_idle += 2970;
    test_now_ms += 30000;
    system_metrics_dispatch_if_due(config, runtime, now + 30);
    assert(runtime->subscriptions[0].last_ok == 0);
    assert(runtime->metrics.last_delivered.cpu_usage_percent == 15.0);
    assert(runtime->metrics.last_delivered_at == now);
    assert(c300x_recent_events_count(&runtime->recent_events) == 1);
    /* Returning to the delivered baseline must not erase the pending state. */
    test_busy += 450;
    test_idle += 2550;
    test_now_ms += 30000;
    system_metrics_dispatch_if_due(config, runtime, now + 60);
    assert(c300x_recent_events_count(&runtime->recent_events) == 2);
    c300x_recent_events_clear(&runtime->recent_events);
}

static pid_t start_callback(struct agent_runtime *runtime, const char *status)
{
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    socklen_t address_size = sizeof(address);
    assert(fd >= 0);
    assert(bind(fd, (struct sockaddr *)&address, sizeof(address)) == 0);
    assert(getsockname(fd, (struct sockaddr *)&address, &address_size) == 0);
    assert(listen(fd, 1) == 0);
    snprintf(runtime->subscriptions[0].callback_url,
        sizeof(runtime->subscriptions[0].callback_url), "http://127.0.0.1:%u/callback", ntohs(address.sin_port));
    pid_t child = fork();
    assert(child >= 0);
    if (child == 0) {
        alarm(5);
        int client = accept(fd, NULL, NULL);
        char request[8192];
        int too_large = 0;
        assert(client >= 0);
        assert(receive_http_request(client, request, sizeof(request), &too_large));
        assert(strstr(request, "system.metrics_changed") != NULL);
        assert(send_all_bytes(client, "HTTP/1.", 7));
        usleep(1000);
        assert(send_all_bytes(client, status, strlen(status)));
        close(client);
        close(fd);
        _exit(0);
    }
    close(fd);
    return child;
}

static void finish_callback(pid_t child)
{
    int status = 0;
    assert(waitpid(child, &status, 0) == child);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
}

static void check_success_and_http_error(struct c300x_config *config, struct agent_runtime *runtime, time_t now)
{
    baseline(config, runtime, now, 15.0);
    pid_t child = start_callback(runtime, "1 503 Unavailable\r\nContent-Length: 0\r\n\r\n");
    test_busy += 30;
    test_idle += 2970;
    test_now_ms += 30000;
    system_metrics_dispatch_if_due(config, runtime, now + 30);
    finish_callback(child);
    assert(runtime->metrics.last_delivered.cpu_usage_percent == 15.0);
    assert(runtime->subscriptions[0].last_delivered_at[0] == '\0');

    child = start_callback(runtime, "1 200 OK\r\nContent-Length: 2\r\n\r\n{}");
    test_busy += 60;
    test_idle += 2940;
    test_now_ms += 30000;
    system_metrics_dispatch_if_due(config, runtime, now + 60);
    finish_callback(child);
    assert(runtime->metrics.last_delivered.cpu_usage_percent == 2.0);
    assert(runtime->metrics.last_delivered_at == now + 60);
    assert(runtime->metrics.delivery_pending == 0);
    assert(runtime->subscriptions[0].last_ok == 1);
    assert(runtime->subscriptions[0].last_delivered_at[0] != '\0');

    int count = c300x_recent_events_count(&runtime->recent_events);
    test_busy += 60;
    test_idle += 2940;
    test_now_ms += 30000;
    system_metrics_dispatch_if_due(config, runtime, now + 90);
    assert(c300x_recent_events_count(&runtime->recent_events) == count);
    c300x_recent_events_clear(&runtime->recent_events);
}

static void check_sampling_and_clock(struct c300x_config *config, struct agent_runtime *runtime, time_t now)
{
    baseline(config, runtime, now, 1.0);
    long long due = runtime->metrics.next_sample_ms;
    unsigned long long sequence = runtime->metrics.last.sample_sequence;
    strcpy(runtime->subscriptions[0].callback_url, "invalid");
    test_busy += 2;
    test_idle += 8;
    system_metrics_dispatch_now(config, runtime, now);
    assert(runtime->metrics.next_sample_ms == due);
    assert(runtime->metrics.last.sample_sequence == sequence);
    system_metrics_dispatch_if_due(config, runtime, now + 36000);
    assert(runtime->metrics.last.sample_sequence == sequence);
    test_busy += 28;
    test_idle += 2962;
    test_now_ms += 30000;
    system_metrics_dispatch_if_due(config, runtime, now - 36000);
    assert(runtime->metrics.last.sample_sequence == sequence + 1);
    assert(runtime->metrics.last.sample_interval_ms == 30000);
    assert(runtime->metrics.last.cpu_usage_percent == 1.0);
    char json[2048];
    test_now_ms += 125;
    assert(c300x_system_metrics_json(&runtime->metrics.last, 1, json, sizeof(json)));
    assert(strstr(json, "\"sample_age_ms\":125") != NULL);
    assert(strstr(json, "\"sample_sequence\":2") != NULL);
    c300x_recent_events_clear(&runtime->recent_events);
}

static void check_initial_and_precision(struct c300x_config *config, struct agent_runtime *runtime)
{
    memset(runtime, 0, sizeof(*runtime));
    assert(c300x_system_metrics_monitor_init(config, &runtime->metrics));
    char first_instance[33];
    strcpy(first_instance, runtime->metrics.last.instance_id);
    assert(strlen(first_instance) == 32);
    assert(!runtime->metrics.last.has_cpu_usage);
    assert(runtime->metrics.last.sample_sequence == 1);
    assert(c300x_system_metrics_monitor_init(config, &runtime->metrics));
    assert(strcmp(first_instance, runtime->metrics.last.instance_id) != 0);

    struct system_metrics_sample previous = runtime->metrics.last;
    previous.has_cpu_usage = 1;
    previous.cpu_usage_percent = 1.0;
    struct system_metrics_sample current = previous;
    current.cpu_usage_percent = 1.04;
    assert(!c300x_system_metrics_changed(config, &previous, &current));
    current.cpu_usage_percent = 1.06;
    assert(c300x_system_metrics_changed(config, &previous, &current));
    current = previous;
    current.has_cpu_usage = 0;
    assert(c300x_system_metrics_changed(config, &previous, &current));
}

static void check_heartbeat_and_watchdog(struct c300x_config *config, struct agent_runtime *runtime, time_t now)
{
    baseline(config, runtime, now, 1.0);
    strcpy(runtime->subscriptions[0].callback_url, "invalid");
    for (int index = 1; index <= 20; index++) {
        test_now_ms += 30000;
        test_busy += 30;
        test_idle += 2970;
        system_metrics_dispatch_if_due(config, runtime, now + index * 30);
        assert(c300x_recent_events_count(&runtime->recent_events) == (index == 20 ? 1 : 0));
    }
    c300x_recent_events_clear(&runtime->recent_events);
    baseline(config, runtime, now, 95.0);
    strcpy(runtime->subscriptions[0].callback_url, "invalid");
    test_now_ms += 30000;
    test_busy += 2850;
    test_idle += 150;
    system_metrics_dispatch_if_due(config, runtime, now + 30);
    assert(c300x_recent_events_count(&runtime->recent_events) == 1);
    assert(runtime->metrics.high_cpu_since == now + 30);
    c300x_recent_events_clear(&runtime->recent_events);
}

static void check_hourly_budget(struct c300x_config *config, struct agent_runtime *runtime, time_t now)
{
    for (int scenario = 0; scenario < 4; scenario++) {
        baseline(config, runtime, now, 1.0);
        runtime->subscription_count = scenario == 3 ? 0 : 1;
        unsigned proc_before = test_proc_reads;
        unsigned temperature_before = test_temperature_reads;
        unsigned random_before = test_random_reads;
        unsigned dispatches = 0;
        size_t payload_bytes = 0;
        for (int second = 1; second <= 3600; second++) {
            test_now_ms += 1000;
            if (second % 30 == 0) {
                unsigned busy = scenario == 1 && second % 60 == 0 ? 33 : 30;
                test_busy += busy;
                test_idle += 3000 - busy;
            }
            if (scenario == 3) {
                system_metrics_dispatch_if_due(config, runtime, now + second);
            } else if (c300x_system_metrics_monitor_tick(config, &runtime->metrics, NULL, now + second)) {
                assert(second % 30 == 0);
                char json[2048];
                assert(c300x_system_metrics_json(&runtime->metrics.last, 0, json, sizeof(json)));
                payload_bytes += strlen(json);
                dispatches++;
                if (scenario == 2) {
                    runtime->metrics.delivery_pending = 1;
                } else {
                    c300x_system_metrics_monitor_delivered(&runtime->metrics, now + second);
                }
            }
            assert(c300x_system_metrics_monitor_timeout_ms(&runtime->metrics) > 0);
        }
        assert(runtime->metrics.last.sample_sequence == 121);
        assert(test_proc_reads - proc_before == 360);
        assert(test_temperature_reads - temperature_before == 240);
        assert(test_random_reads == random_before);
        assert(c300x_recent_events_count(&runtime->recent_events) == 0);
        /* Failed heartbeats recur only on regular samples, not every loop tick. */
        assert(dispatches == (scenario == 0 ? 6u : scenario == 1 ? 119u : scenario == 2 ? 101u : 0u));
        printf("metrics audit scenario=%d samples=120 dispatches=%u metric_json_bytes=%zu\n",
            scenario, dispatches, payload_bytes);
    }
}

int main(void)
{
    struct c300x_config config;
    struct agent_runtime *runtime = calloc(1, sizeof(*runtime));
    time_t now = time(NULL);
    c300x_default_config(&config);
    config.mqtt_enabled = 0;
    assert(runtime != NULL);
    check_http_snapshot(&config, runtime, now);
    check_failed_push(&config, runtime, now);
    check_success_and_http_error(&config, runtime, now);
    check_sampling_and_clock(&config, runtime, now);
    check_initial_and_precision(&config, runtime);
    check_heartbeat_and_watchdog(&config, runtime, now);
    check_hourly_budget(&config, runtime, now);
    free(runtime);
    return 0;
}
