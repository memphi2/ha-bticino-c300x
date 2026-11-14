#include "aswm_snapshot.h"

#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define ASWM_RAW_PATH "/tmp/aswm.raw"
#define ASWM_SNAPSHOT_PATH "/tmp/c300x-doorbell-snapshot.jpg"
#define ASWM_LOCK_PATH "/tmp/c300x-doorbell-snapshot.lock"
#define ASWM_FFMPEG_PATH "/home/bticino/cfg/extra/c300x-controller/ffmpeg"
#define ASWM_SYSTEM_FFMPEG_PATH "/usr/bin/ffmpeg"
#define ASWM_MAX_RETRIES 20
#define ASWM_DELAY_SECONDS 1
#define ASWM_STABLE_DELAY_SECONDS 1
#define ASWM_FFMPEG_TIMEOUT_SECONDS 5

struct snapshot_reference {
    int existed;
    ino_t inode;
    off_t size;
    time_t mtime;
    time_t ctime;
    unsigned long fingerprint;
};

static pthread_mutex_t snapshot_mutex = PTHREAD_MUTEX_INITIALIZER;
static int snapshot_running;

const char *c300x_aswm_snapshot_path(void)
{
    return ASWM_SNAPSHOT_PATH;
}

static unsigned long raw_fingerprint(void)
{
    FILE *raw_file = fopen(ASWM_RAW_PATH, "rb");
    unsigned char buffer[4096];
    unsigned long fingerprint = 2166136261UL;
    size_t bytes_read;

    if (raw_file == NULL) return 0;
    while ((bytes_read = fread(buffer, 1, sizeof(buffer), raw_file)) > 0) {
        for (size_t index = 0; index < bytes_read; index++) {
            fingerprint ^= buffer[index];
            fingerprint *= 16777619UL;
        }
    }
    fclose(raw_file);
    return fingerprint;
}

static int file_size(const char *path, off_t *size)
{
    struct stat info;
    if (stat(path, &info) != 0 || !S_ISREG(info.st_mode) || info.st_size <= 0) {
        return 0;
    }
    *size = info.st_size;
    return 1;
}

static int acquire_lock(int fd)
{
    struct flock lock = {0};
    lock.l_type = F_WRLCK;
    lock.l_whence = SEEK_SET;
    return fcntl(fd, F_SETLK, &lock);
}

static void release_lock(int fd)
{
    struct flock lock = {0};
    lock.l_type = F_UNLCK;
    lock.l_whence = SEEK_SET;
    (void)fcntl(fd, F_SETLK, &lock);
}

static void read_snapshot_reference(struct snapshot_reference *reference)
{
    struct stat status;
    memset(reference, 0, sizeof(*reference));
    if (stat(ASWM_RAW_PATH, &status) != 0 || !S_ISREG(status.st_mode)) return;
    reference->existed = 1;
    reference->inode = status.st_ino;
    reference->size = status.st_size;
    reference->mtime = status.st_mtime;
    reference->ctime = status.st_ctime;
    reference->fingerprint = raw_fingerprint();
}

static int raw_file_changed(const struct snapshot_reference *reference)
{
    struct stat status;
    if (stat(ASWM_RAW_PATH, &status) != 0 || !S_ISREG(status.st_mode)) return 0;
    if (!reference->existed) return 1;
    return status.st_ino != reference->inode
        || status.st_size != reference->size
        || status.st_mtime != reference->mtime
        || status.st_ctime != reference->ctime
        || raw_fingerprint() != reference->fingerprint;
}

static int raw_file_is_stable(const struct snapshot_reference *reference)
{
    struct stat initial;
    unsigned long initial_fingerprint;
    unsigned long final_fingerprint;
    off_t initial_size = 0;
    off_t final_size = 0;

    if (stat(ASWM_RAW_PATH, &initial) != 0 || !S_ISREG(initial.st_mode)) return 0;
    if (!raw_file_changed(reference)) return 0;
    if (!file_size(ASWM_RAW_PATH, &initial_size)) return 0;
    initial_fingerprint = raw_fingerprint();
    sleep(ASWM_STABLE_DELAY_SECONDS);
    final_fingerprint = raw_fingerprint();
    return file_size(ASWM_RAW_PATH, &final_size)
        && final_size == initial_size
        && final_fingerprint == initial_fingerprint;
}

static int wait_for_child(pid_t child)
{
    time_t deadline = time(NULL) + ASWM_FFMPEG_TIMEOUT_SECONDS;
    int status = 0;

    while (time(NULL) <= deadline) {
        pid_t result = waitpid(child, &status, WNOHANG);
        if (result == child) {
            return WIFEXITED(status) && WEXITSTATUS(status) == 0;
        }
        if (result < 0) {
            return 0;
        }
        sleep(1);
    }
    (void)kill(child, SIGKILL);
    (void)waitpid(child, &status, 0);
    return 0;
}

static void exec_ffmpeg(const char *path, const char *temporary_path)
{
    execl(
        path,
        path,
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "yuv420p",
        "-s",
        "688x480",
        "-i",
        ASWM_RAW_PATH,
        "-frames:v",
        "1",
        "-q:v",
        "5",
        "-vf",
        "scale=640:360",
        "-f",
        "mjpeg",
        temporary_path,
        (char *)NULL
    );
    _exit(127);
}

static int run_ffmpeg(const char *path, const char *temporary_path)
{
    pid_t child = fork();
    if (child == 0) exec_ffmpeg(path, temporary_path);
    return child > 0 && wait_for_child(child);
}

static void convert_raw_to_snapshot(const char *temporary_path)
{
    struct stat output;
    int converted = run_ffmpeg(ASWM_FFMPEG_PATH, temporary_path);
    if (!converted) converted = run_ffmpeg(ASWM_SYSTEM_FFMPEG_PATH, temporary_path);
    if (converted && stat(temporary_path, &output) == 0 && output.st_size > 0) {
        (void)rename(temporary_path, ASWM_SNAPSHOT_PATH);
    }
    unlink(temporary_path);
}

struct snapshot_request {
    struct snapshot_reference reference;
};

static void *snapshot_worker(void *request_data)
{
    struct snapshot_request *request = request_data;
    int lock_fd = open(ASWM_LOCK_PATH, O_CREAT | O_WRONLY, 0600);
    char temporary_path[sizeof(ASWM_SNAPSHOT_PATH) + 8];

    if (lock_fd < 0 || acquire_lock(lock_fd) != 0) {
        if (lock_fd >= 0) close(lock_fd);
        goto finished;
    }
    for (int attempt = 0; attempt < ASWM_MAX_RETRIES; attempt++) {
        if (raw_file_is_stable(&request->reference)) {
            snprintf(temporary_path, sizeof(temporary_path), "%s.tmp", ASWM_SNAPSHOT_PATH);
            convert_raw_to_snapshot(temporary_path);
            break;
        }
        sleep(ASWM_DELAY_SECONDS);
    }
    release_lock(lock_fd);
    close(lock_fd);
finished:
    free(request);
    pthread_mutex_lock(&snapshot_mutex);
    snapshot_running = 0;
    pthread_mutex_unlock(&snapshot_mutex);
    return NULL;
}

void c300x_aswm_snapshot_start(void)
{
    struct snapshot_request *request = calloc(1, sizeof(*request));
    pthread_t thread;
    pthread_attr_t attributes;
    int create_result;

    if (request == NULL) return;
    pthread_mutex_lock(&snapshot_mutex);
    if (snapshot_running) {
        pthread_mutex_unlock(&snapshot_mutex);
        free(request);
        return;
    }
    read_snapshot_reference(&request->reference);
    unlink(ASWM_SNAPSHOT_PATH);
    snapshot_running = 1;
    pthread_mutex_unlock(&snapshot_mutex);
    if (pthread_attr_init(&attributes) != 0) {
        goto failed;
    }
    (void)pthread_attr_setdetachstate(&attributes, PTHREAD_CREATE_DETACHED);
    create_result = pthread_create(&thread, &attributes, snapshot_worker, request);
    pthread_attr_destroy(&attributes);
    if (create_result == 0) {
        return;
    }
failed:
    free(request);
    pthread_mutex_lock(&snapshot_mutex);
    snapshot_running = 0;
    pthread_mutex_unlock(&snapshot_mutex);
}
