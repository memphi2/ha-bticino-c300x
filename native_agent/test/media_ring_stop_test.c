/* Production receiver stop with deterministic cleanup/descriptor reuse. */
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sys/socket.h>

static int tracked_unlock(pthread_mutex_t *);
static int tracked_join(pthread_t, void **);
#define pthread_mutex_unlock tracked_unlock
#define pthread_join tracked_join
#undef _POSIX_C_SOURCE
#include "../src/media_bridge.c"
#undef pthread_mutex_unlock
#undef pthread_join

static pthread_t stopping_thread;
static atomic_bool cleanup_go, cleanup_done;
static int original_fd, replacement_fd, armed, joins;

static int tracked_unlock(pthread_mutex_t *lock)
{
    int result = pthread_mutex_unlock(lock);
    if (lock == &g_bridge.mutex && pthread_equal(pthread_self(), stopping_thread) && armed) {
        armed = 0;
        atomic_store(&cleanup_go, true);
        while (!atomic_load(&cleanup_done)) usleep(1000);
    }
    return result;
}

static int tracked_join(pthread_t thread, void **result)
{
    /* Waiting for the receiver under its ownership lock would deadlock. */
    assert(pthread_mutex_trylock(&g_bridge.mutex) == 0);
    pthread_mutex_unlock(&g_bridge.mutex);
    joins++;
    return pthread_join(thread, result);
}

static void *receiver_cleanup(void *unused)
{
    (void)unused;
    while (!atomic_load(&cleanup_go)) usleep(1000);
    pthread_mutex_lock(&g_bridge.mutex);
    assert(g_bridge.ring_stop);
    /* Same publication/close ordering as ring_receiver_thread cleanup. */
    g_bridge.ring_sip_fd = -1;
    g_bridge.ring_registered = false;
    pthread_mutex_unlock(&g_bridge.mutex);
    shutdown(original_fd, SHUT_RDWR);
    close(original_fd);
    assert(dup2(replacement_fd, original_fd) == original_fd);
    atomic_store(&cleanup_done, true);
    return NULL;
}

void c300x_video_bridge_media_stopped(struct c300x_video *video)
{
    assert(video == g_bridge.video);
}

int main(void)
{
    int original[2], replacement[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, original) == 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, replacement) == 0);
    original_fd = original[0];
    replacement_fd = replacement[0];
    stopping_thread = pthread_self();
    g_bridge.video = (struct c300x_video *)&original;
    g_bridge.running = true;
    g_bridge.ring_started = true;
    g_bridge.ring_registered = true;
    g_bridge.ring_sip_fd = original_fd;
    assert(pthread_create(&g_bridge.ring_thread, NULL, receiver_cleanup, NULL) == 0);
    armed = 1;
    c300x_media_ring_receiver_stop(g_bridge.video);
    assert(joins == 1 && atomic_load(&cleanup_done));
    char byte;
    assert(recv(original[1], &byte, 1, MSG_DONTWAIT) == 0);
    assert(recv(replacement[1], &byte, 1, MSG_DONTWAIT) == -1);
    assert(errno == EAGAIN || errno == EWOULDBLOCK);
    assert(send(original_fd, "x", 1, MSG_NOSIGNAL) == 1);
    assert(recv(replacement[1], &byte, 1, 0) == 1 && byte == 'x');
    assert(g_bridge.ring_sip_fd == -1 && !g_bridge.ring_started);
    c300x_media_ring_receiver_stop(g_bridge.video);
    assert(joins == 1);
    close(original_fd); close(original[1]);
    close(replacement[0]); close(replacement[1]);
    return 0;
}
