/* The ring answer wait is bounded by the monotonic clock, not the wall clock. */
#include <assert.h>
#include <stdatomic.h>
#include <time.h>
static int test_clock_gettime(clockid_t, struct timespec *);
#define clock_gettime test_clock_gettime
#undef _POSIX_C_SOURCE
#include "../src/media_bridge.c"
#undef clock_gettime

/* clock_step: the wall clock was set an hour ahead while the agent runs. */
static long wall_offset;
static int test_clock_gettime(clockid_t clock, struct timespec *now) {
    int result = clock_gettime(clock, now);
    if (result == 0 && clock == CLOCK_REALTIME) now->tv_sec += wall_offset;
    return result;
}

bool c300x_device_media_takeover(const struct c300x_config *config, c300x_device_media_video_wait_fn wait, void *context) { (void)config; (void)wait; (void)context; return false; }
void c300x_device_media_stop(const struct c300x_config *config) { (void)config; }
bool c300x_device_media_start(const struct c300x_config *config) { (void)config; return true; }
int c300x_device_user_media_identity(const char *hint, struct c300x_device_user_identity *identity) {
    (void)hint; (void)identity;
    return 0;
}

static atomic_bool returned;
static void *answer_worker(void *arg) {
    (void)arg;
    assert(request_ring_answer_if_active(&g_bridge));
    atomic_store(&returned, true);
    return NULL;
}

static void ring_active(void) {
    pthread_mutex_lock(&g_bridge.mutex);
    g_bridge.ring_call_active = true;
    g_bridge.ring_answered = false;
    g_bridge.ring_call_stop = false;
    pthread_mutex_unlock(&g_bridge.mutex);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    struct c300x_config config;
    c300x_default_config(&config);
    g_bridge.config = &config;
    g_bridge.video = c300x_video_create(&config, NULL, 0);
    assert(g_bridge.video);
    alarm(10);
    pthread_t worker;
    wall_offset = strcmp(argv[1], "clock_step") == 0 ? 3600 : 0;
    (void)test_clock_gettime; /* Unused once nothing here reads the wall clock. */
    ring_active();
    long long start = c300x_monotonic_ms();
    assert(pthread_create(&worker, NULL, answer_worker, NULL) == 0);
    if (strcmp(argv[1], "clock_step") == 0) {
        /* Nobody answers: the wait ends after its two seconds. */
        assert(pthread_join(worker, NULL) == 0);
        long long elapsed = c300x_monotonic_ms() - start;
        assert(elapsed >= 1900 && elapsed < 3000);
    } else if (strcmp(argv[1], "cleanup") == 0) {
        /* The call ends while the answer is pending: the wait ends with it. */
        usleep(100000);
        assert(!atomic_load(&returned));
        ring_call_cleanup(&g_bridge);
        assert(pthread_join(worker, NULL) == 0);
        assert(c300x_monotonic_ms() - start < 1000);
    } else {
        return 2;
    }
    return 0;
}
