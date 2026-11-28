/* The real RTSP listener: accept errors and the connection limit. */
#include <assert.h>
#include <errno.h>
#include <netinet/tcp.h>
#include <stdatomic.h>
#include <sys/socket.h>
static int test_accept(int, struct sockaddr *, socklen_t *);
#define accept test_accept
#undef _POSIX_C_SOURCE
#include "../src/media_bridge.c"
#undef accept

static atomic_int accept_calls, accept_failures;
static const int accept_errors[] = {EMFILE, ECONNABORTED, ENFILE, ENOBUFS, ENOMEM, EPROTO};

static int test_accept(int fd, struct sockaddr *address, socklen_t *size) {
    int call = atomic_fetch_add(&accept_calls, 1);
    if (call < atomic_load(&accept_failures)) {
        errno = accept_errors[call % (int)(sizeof(accept_errors) / sizeof(accept_errors[0]))];
        return -1;
    }
    return accept(fd, address, size);
}

bool c300x_device_media_takeover(const struct c300x_config *config, c300x_device_media_video_wait_fn wait, void *context) { (void)config; (void)wait; (void)context; return false; }
void c300x_device_media_stop(const struct c300x_config *config) { (void)config; }
bool c300x_device_media_start(const struct c300x_config *config) { (void)config; return true; }
int c300x_device_user_media_identity(const char *hint, struct c300x_device_user_identity *identity) {
    (void)hint; (void)identity;
    return 0;
}

static unsigned listener_port(void) {
    struct sockaddr_storage address;
    socklen_t len = sizeof(address);
    pthread_mutex_lock(&g_bridge.mutex);
    assert(g_bridge.listen_fd >= 0);
    assert(getsockname(g_bridge.listen_fd, (struct sockaddr *)&address, &len) == 0);
    pthread_mutex_unlock(&g_bridge.mutex);
    return address.ss_family == AF_INET6
        ? ntohs(((struct sockaddr_in6 *)&address)->sin6_port)
        : ntohs(((struct sockaddr_in *)&address)->sin_port);
}

static int connect_client(unsigned port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons((uint16_t)port)};
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    assert(fd >= 0);
    struct timeval timeout = {5, 0};
    assert(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        close(fd);
        return -1;
    }
    return fd;
}

/* The listener answers OPTIONS on this connection. */
static bool options_answered(int fd) {
    const char *options = "OPTIONS * RTSP/1.0\r\nCSeq: 1\r\n\r\n";
    char response[512] = {0};
    if (send(fd, options, strlen(options), MSG_NOSIGNAL) != (ssize_t)strlen(options)) return false;
    ssize_t got = recv(fd, response, sizeof(response) - 1, 0);
    return got > 0 && strncmp(response, "RTSP/1.0 200", 12) == 0;
}

static int connections(void) {
    pthread_mutex_lock(&g_bridge.mutex);
    int count = g_bridge.rtsp_client_threads;
    pthread_mutex_unlock(&g_bridge.mutex);
    return count;
}

static void wait_connections(int count) {
    for (int i = 0; i < 500 && connections() != count; i++) usleep(2000);
    assert(connections() == count);
}

static bool closed_by_peer(int fd) {
    char byte;
    return recv(fd, &byte, 1, 0) == 0;
}

static bool authenticated_request(int fd) {
    const char *request = "GET_PARAMETER rtsp://127.0.0.1/doorbell-video RTSP/1.0\r\nCSeq: 2\r\n"
        "Authorization: Basic dXNlcjpwYXNz\r\n\r\n";
    char response[512] = {0};
    if (send(fd, request, strlen(request), MSG_NOSIGNAL) != (ssize_t)strlen(request)) return false;
    ssize_t got = recv(fd, response, sizeof(response) - 1, 0);
    return got > 0 && strncmp(response, "RTSP/1.0 ", 9) == 0 && strstr(response, " 401 ") == NULL;
}

/* A full table of connections that never authenticate must not keep Home
 * Assistant out: the oldest of them gives way, an authenticated one stays. */
static void unauth_eviction_test(struct c300x_config *config, struct c300x_video *video) {
    strcpy(config->video_rtsp_username, "user");
    strcpy(config->video_rtsp_password, "pass");
    assert(c300x_media_bridge_start(config, video));
    unsigned port = listener_port();
    int authenticated = connect_client(port);
    assert(authenticated >= 0 && authenticated_request(authenticated));
    int idle[RTSP_CONNECTION_LIMIT - 1];
    for (int i = 0; i < RTSP_CONNECTION_LIMIT - 1; i++) {
        idle[i] = connect_client(port);
        assert(idle[i] >= 0);
        wait_connections(i + 2);
        usleep(5000);
    }
    int fresh = connect_client(port);
    assert(fresh >= 0);
    assert(options_answered(fresh));
    assert(closed_by_peer(idle[0]));
    assert(authenticated_request(authenticated));
    wait_connections(RTSP_CONNECTION_LIMIT);
    close(fresh);
    close(authenticated);
    for (int i = 0; i < RTSP_CONNECTION_LIMIT - 1; i++) close(idle[i]);
    c300x_media_bridge_stop(video);
}

/* c300x_video_create starts the listener; the failures are armed before. */
static void accept_error_test(struct c300x_config *config, struct c300x_video *video) {
    assert(c300x_media_bridge_start(config, video));
    unsigned port = listener_port();
    for (int i = 0; i < 300 && atomic_load(&accept_calls) <= atomic_load(&accept_failures); i++) {
        usleep(10000);
    }
    /* Twelve failed accepts later the listener still takes connections. */
    int fd = connect_client(port);
    assert(fd >= 0);
    assert(options_answered(fd));
    close(fd);
    c300x_media_bridge_stop(video);
    pthread_mutex_lock(&g_bridge.mutex);
    assert(!g_bridge.running && g_bridge.listen_fd < 0);
    pthread_mutex_unlock(&g_bridge.mutex);
}

/* Interleaved media goes out as each packet arrives: no connection waits for
 * the client's ACK before sending a small packet. */
static void nodelay_test(struct c300x_config *config, struct c300x_video *video) {
    assert(c300x_media_bridge_start(config, video));
    int fd = connect_client(listener_port());
    assert(fd >= 0 && options_answered(fd));
    int checked = 0;
    pthread_mutex_lock(&g_bridge.mutex);
    for (int i = 0; i < RTSP_CONNECTION_LIMIT; i++) {
        if (g_bridge.rtsp_connection_fds[i] == 0) continue;
        int value = 0;
        socklen_t size = sizeof(value);
        assert(getsockopt(g_bridge.rtsp_connection_fds[i] - 1, IPPROTO_TCP, TCP_NODELAY, &value, &size) == 0);
        assert(value != 0);
        checked++;
    }
    pthread_mutex_unlock(&g_bridge.mutex);
    assert(checked == 1);
    close(fd);
    c300x_media_bridge_stop(video);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    struct c300x_config config;
    c300x_default_config(&config);
    config.video_enabled = 1;
    config.video_rtsp_port = 0;
    alarm(20);
    if (strcmp(argv[1], "accept_error") == 0) atomic_store(&accept_failures, 12);
    struct c300x_video *video = c300x_video_create(&config, NULL, 0);
    assert(video);
    if (strcmp(argv[1], "accept_error") == 0) {
        accept_error_test(&config, video);
    } else if (strcmp(argv[1], "unauth_eviction") == 0) {
        unauth_eviction_test(&config, video);
    } else if (strcmp(argv[1], "nodelay") == 0) {
        nodelay_test(&config, video);
    } else {
        return 2;
    }
    c300x_video_destroy(video);
    return 0;
}
