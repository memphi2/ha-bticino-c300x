#include "system_metrics.h"

#include "string_util.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

static double read_temperature_c(const char **source)
{
    const char *paths[] = {
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/devices/virtual/thermal/thermal_zone0/temp",
        NULL,
    };
    for (size_t index = 0; paths[index] != NULL; index++) {
        FILE *file = fopen(paths[index], "r");
        double value;
        if (file == NULL) {
            continue;
        }
        if (fscanf(file, "%lf", &value) == 1) {
            fclose(file);
            *source = paths[index];
            if (value > 1000.0 || value < -1000.0) {
                value /= 1000.0;
            }
            return value;
        }
        fclose(file);
    }
    *source = NULL;
    return -100000.0;
}

static long online_cpu_count(void)
{
    long count = sysconf(_SC_NPROCESSORS_ONLN);
    return count > 0 ? count : 1;
}

static double load_percent(double load_average, long cpu_count)
{
    if (cpu_count <= 0 || load_average < 0.0) {
        return 0.0;
    }
    return (load_average / (double)cpu_count) * 100.0;
}

static int read_cpu_jiffies(unsigned long long *total, unsigned long long *idle)
{
    FILE *file = fopen("/proc/stat", "r");
    char label[8];
    unsigned long long user;
    unsigned long long nice;
    unsigned long long system;
    unsigned long long idle_time;
    unsigned long long iowait;
    unsigned long long irq;
    unsigned long long softirq;
    unsigned long long steal;
    int fields;

    if (file == NULL) {
        return 0;
    }
    fields = fscanf(
        file,
        "%7s %llu %llu %llu %llu %llu %llu %llu %llu",
        label,
        &user,
        &nice,
        &system,
        &idle_time,
        &iowait,
        &irq,
        &softirq,
        &steal
    );
    fclose(file);
    if (fields < 5 || strcmp(label, "cpu") != 0) {
        return 0;
    }
    if (fields < 6) {
        iowait = 0;
    }
    if (fields < 7) {
        irq = 0;
    }
    if (fields < 8) {
        softirq = 0;
    }
    if (fields < 9) {
        steal = 0;
    }
    *idle = idle_time + iowait;
    *total = user + nice + system + idle_time + iowait + irq + softirq + steal;
    return *total > 0;
}

static int read_memory_metrics(
    long *total_kb,
    long *available_kb,
    long *used_kb,
    double *usage_percent
)
{
    FILE *file = fopen("/proc/meminfo", "r");
    char line[160];
    long total = -1;
    long available = -1;
    long free_kb = 0;
    long buffers = 0;
    long cached = 0;
    long reclaimable = 0;

    if (file == NULL) {
        return 0;
    }
    while (fgets(line, sizeof(line), file) != NULL) {
        char key[64];
        char unit[16];
        long value;

        if (sscanf(line, "%63s %ld %15s", key, &value, unit) < 2) {
            continue;
        }
        if (strcmp(key, "MemTotal:") == 0) {
            total = value;
        } else if (strcmp(key, "MemAvailable:") == 0) {
            available = value;
        } else if (strcmp(key, "MemFree:") == 0) {
            free_kb = value;
        } else if (strcmp(key, "Buffers:") == 0) {
            buffers = value;
        } else if (strcmp(key, "Cached:") == 0) {
            cached = value;
        } else if (strcmp(key, "SReclaimable:") == 0) {
            reclaimable = value;
        }
    }
    fclose(file);
    if (total <= 0) {
        return 0;
    }
    if (available < 0) {
        available = free_kb + buffers + cached + reclaimable;
    }
    if (available < 0) {
        available = 0;
    }
    if (available > total) {
        available = total;
    }
    *total_kb = total;
    *available_kb = available;
    *used_kb = total - available;
    *usage_percent = ((double)*used_kb / (double)total) * 100.0;
    return 1;
}

int c300x_system_metrics_read_sample(
    struct system_metrics_sample *sample,
    const struct system_metrics_sample *previous
)
{
    double loads[3] = {0.0, 0.0, 0.0};
    double temperature;
    const char *temperature_source = NULL;
    FILE *load_file;

    memset(sample, 0, sizeof(*sample));
    load_file = fopen("/proc/loadavg", "r");
    if (load_file != NULL) {
        if (fscanf(load_file, "%lf %lf %lf", &loads[0], &loads[1], &loads[2]) != 3) {
            loads[0] = 0.0;
            loads[1] = 0.0;
            loads[2] = 0.0;
        }
        fclose(load_file);
    }
    sample->cpu_count = online_cpu_count();
    if (read_cpu_jiffies(&sample->cpu_total_jiffies, &sample->cpu_idle_jiffies)) {
        sample->has_cpu_jiffies = 1;
        if (
            previous != NULL
            && previous->has_cpu_jiffies
            && sample->cpu_total_jiffies > previous->cpu_total_jiffies
            && sample->cpu_idle_jiffies >= previous->cpu_idle_jiffies
        ) {
            unsigned long long total_delta = sample->cpu_total_jiffies - previous->cpu_total_jiffies;
            unsigned long long idle_delta = sample->cpu_idle_jiffies - previous->cpu_idle_jiffies;
            if (total_delta > 0 && idle_delta <= total_delta) {
                sample->cpu_usage_percent = ((double)(total_delta - idle_delta) / (double)total_delta) * 100.0;
                sample->has_cpu_usage = 1;
            }
        }
    }
    sample->load_1m = loads[0];
    sample->load_5m = loads[1];
    sample->load_15m = loads[2];
    sample->load_1m_percent = load_percent(loads[0], sample->cpu_count);
    sample->load_5m_percent = load_percent(loads[1], sample->cpu_count);
    sample->load_15m_percent = load_percent(loads[2], sample->cpu_count);
    if (read_memory_metrics(
        &sample->memory_total_kb,
        &sample->memory_available_kb,
        &sample->memory_used_kb,
        &sample->memory_usage_percent
    )) {
        sample->has_memory = 1;
    }
    temperature = read_temperature_c(&temperature_source);
    if (temperature_source != NULL) {
        sample->has_temperature = 1;
        sample->temperature_c = temperature;
        c300x_copy_string(
            sample->temperature_source,
            sizeof(sample->temperature_source),
            temperature_source
        );
    }
    return 1;
}

int c300x_system_metrics_json(
    const struct system_metrics_sample *sample,
    int include_ok,
    char *body,
    size_t body_len
)
{
    const char *prefix = include_ok ? "{\"ok\":true," : "{";
    char cpu_usage_json[512];
    char memory_json[1024];
    char temperature_json[2048];
    size_t used = 0;

    if (sample->has_cpu_usage) {
        snprintf(cpu_usage_json, sizeof(cpu_usage_json), "%.1f", sample->cpu_usage_percent);
    } else {
        snprintf(cpu_usage_json, sizeof(cpu_usage_json), "null");
    }
    if (sample->has_memory) {
        snprintf(
            memory_json,
            sizeof(memory_json),
            "\"memory_total_kb\":%ld,\"memory_available_kb\":%ld,\"memory_used_kb\":%ld,\"memory_usage_percent\":%.1f",
            sample->memory_total_kb,
            sample->memory_available_kb,
            sample->memory_used_kb,
            sample->memory_usage_percent
        );
    } else {
        snprintf(
            memory_json,
            sizeof(memory_json),
            "\"memory_total_kb\":null,\"memory_available_kb\":null,\"memory_used_kb\":null,\"memory_usage_percent\":null"
        );
    }
    if (sample->has_temperature) {
        snprintf(
            temperature_json,
            sizeof(temperature_json),
            "\"temperature_c\":%.1f,\"temperature_source\":\"%s\"",
            sample->temperature_c,
            sample->temperature_source
        );
    } else {
        snprintf(
            temperature_json,
            sizeof(temperature_json),
            "\"temperature_c\":null,\"temperature_source\":null"
        );
    }
    return c300x_appendf(
        body,
        body_len,
        &used,
        "%s\"cpu_count\":%ld,\"cpu_usage_percent\":%s,\"load_1m\":%.2f,\"load_5m\":%.2f,\"load_15m\":%.2f,\"load_1m_percent\":%.1f,\"load_5m_percent\":%.1f,\"load_15m_percent\":%.1f,%s,%s}",
        prefix,
        sample->cpu_count,
        cpu_usage_json,
        sample->load_1m,
        sample->load_5m,
        sample->load_15m,
        sample->load_1m_percent,
        sample->load_5m_percent,
        sample->load_15m_percent,
        memory_json,
        temperature_json
    );
}
