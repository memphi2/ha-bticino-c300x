#define _LARGEFILE64_SOURCE 1
#include "display_registration.h"
#include "callback_queue.h"
#include "display_callback.h"
#include "http_util.h"
#include "time_util.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef __arm__
#include <sys/syscall.h>
#endif
#include <unistd.h>

static int registration_path(const struct c300x_config *config, char *path, size_t size)
{
    int n = snprintf(path, size, "%s.display-bridge", config->config_path);
    return config->config_path[0] && n > 0 && (size_t)n < size;
}

static int valid_registration(const char *url, const char *secret)
{
    char host[256], port[16], path[256];
    return *url && *secret && !strpbrk(url, "\r\n") && !strpbrk(secret, "\r\n")
        && strlen(url) < C300X_MAX_URL_LEN && strlen(secret) < C300X_MAX_TOKEN_LEN
        && parse_http_url(url, host, sizeof(host), port, sizeof(port), path, sizeof(path));
}

int c300x_display_registration_load(const struct c300x_config *config,
    char url[C300X_MAX_URL_LEN], char secret[C300X_MAX_TOKEN_LEN])
{
    char path[C300X_MAX_PATH_LEN + 32], data[C300X_MAX_URL_LEN + C300X_MAX_TOKEN_LEN + 2];
    if (!registration_path(config, path, sizeof(path))) return 0;
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return 0;
#ifdef __arm__
    struct stat64 st;
    int stat_ok = syscall(SYS_fstat64, fd, &st) == 0;
#else
    struct stat st;
    int stat_ok = fstat(fd, &st) == 0;
#endif
    size_t used = 0;
    int ok = stat_ok && S_ISREG(st.st_mode) && st.st_uid == geteuid()
        && (st.st_mode & 0777) == 0600 && st.st_size > 0 && (size_t)st.st_size < sizeof(data);
    while (ok && used < (size_t)st.st_size) {
        ssize_t n = read(fd, data + used, (size_t)st.st_size - used);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { ok = 0; break; }
        used += (size_t)n;
    }
    close(fd);
    if (!ok || memchr(data, '\0', used) || data[used - 1] != '\n') return 0;
    data[used - 1] = '\0';
    char *split = strchr(data, '\n');
    if (!split) return 0;
    *split++ = '\0';
    if (!valid_registration(data, split)) return 0;
    memcpy(url, data, strlen(data) + 1);
    memcpy(secret, split, strlen(split) + 1);
    return 1;
}

int c300x_display_registration_save(const struct c300x_config *config,
    const char *url, const char *secret)
{
    char path[C300X_MAX_PATH_LEN + 32], temporary[C300X_MAX_PATH_LEN + 48];
    if (!valid_registration(url, secret) || !registration_path(config, path, sizeof(path))) return 0;
    snprintf(temporary, sizeof(temporary), "%s.XXXXXX", path);
    int fd = mkstemp(temporary);
    if (fd < 0) return 0;
    int ok = fchmod(fd, 0600) == 0 && dprintf(fd, "%s\n%s\n", url, secret) > 0 && fsync(fd) == 0;
    if (close(fd) != 0) ok = 0;
    if (ok && rename(temporary, path) == 0) return 1;
    unlink(temporary);
    return 0;
}

int c300x_display_registration_clear(const struct c300x_config *config)
{
    char path[C300X_MAX_PATH_LEN + 32];
    return registration_path(config, path, sizeof(path)) && (unlink(path) == 0 || errno == ENOENT);
}

static void perform_display_callback(struct c300x_callback_job *job)
{
    job->ok = c300x_display_post(job->url, job->token, job->timeout_ms,
        job->payload, job->response, job->response_len);
}

int c300x_display_callback_submit(struct c300x_callback_queue *queue, const char *url,
    const char *secret, int timeout_ms, const char *body, size_t response_len)
{
    struct c300x_callback_job *job = calloc(1, sizeof(*job));
    if (!job) return 0;
    job->perform = perform_display_callback;
    job->response_len = response_len;
    job->response = calloc(1, response_len);
    snprintf(job->url, sizeof(job->url), "%s", url);
    snprintf(job->token, sizeof(job->token), "%s", secret);
    snprintf(job->payload, sizeof(job->payload), "%s", body);
    job->timeout_ms = timeout_ms;
    job->queued_at = c300x_monotonic_ms();
    if (job->response && c300x_callback_queue_submit(queue, job)) return 1;
    c300x_callback_job_free(job);
    return 0;
}

void c300x_display_boot_notice(struct c300x_callback_queue *queue, const char *url,
    const char *secret, int timeout_ms, const char *instance_id)
{
    char body[96];
    snprintf(body, sizeof(body), "{\"type\":\"agent_started\",\"instance_id\":\"%s\"}", instance_id);
    (void)c300x_display_callback_submit(queue, url, secret, timeout_ms, body, 1024);
}
