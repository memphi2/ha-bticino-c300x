/* Broker resolution and connect never run on the loop thread. */
#include <arpa/inet.h>
#include <assert.h>
#include <netdb.h>
#include <poll.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include "../src/mqtt_bridge.h"
#include "../src/time_util.h"

/* The connect deadline of this build, set by the test's compiler call. The
 * delays below leave whole seconds between "slow" and "too late", so a busy
 * machine does not turn one into the other. */
#define DEADLINE_MS MQTT_RESOLVE_CONNECT_TIMEOUT_MS
#define SLOW_MS 500
_Static_assert(DEADLINE_MS >= SLOW_MS + 1500, "the deadline must leave room after a slow answer");

/* A DNS server that takes its time. */
static atomic_int resolve_delay_ms, resolving;
int __real_getaddrinfo(const char *, const char *, const struct addrinfo *, struct addrinfo **);
int __wrap_getaddrinfo(const char *host, const char *port, const struct addrinfo *hints, struct addrinfo **result)
{
    atomic_fetch_add(&resolving, 1);
    usleep((useconds_t)atomic_load(&resolve_delay_ms) * 1000);
    int status = __real_getaddrinfo(host, port, hints, result);
    atomic_fetch_sub(&resolving, 1);
    return status;
}

static int broker(uint16_t *port)
{
    struct sockaddr_in address = {.sin_family = AF_INET};
    socklen_t len = sizeof(address);
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    assert(fd >= 0 && bind(fd, (struct sockaddr *)&address, sizeof(address)) == 0 && listen(fd, 4) == 0);
    assert(getsockname(fd, (struct sockaddr *)&address, &len) == 0);
    *port = ntohs(address.sin_port);
    return fd;
}

static void config_for(struct c300x_config *config, uint16_t port)
{
    memset(config, 0, sizeof(*config));
    config->mqtt_enabled = 1;
    config->mqtt_port = port;
    config->mqtt_keepalive_seconds = 30;
    config->mqtt_reconnect_initial_seconds = 5;
    config->mqtt_reconnect_max_seconds = 60;
    strcpy(config->mqtt_host, "localhost");
    strcpy(config->mqtt_client_id, "client");
}

static void wait_resolvers_gone(void)
{
    for (int i = 0; i < 500 && atomic_load(&resolving) > 0; i++) usleep(10000);
    usleep(50000);
}

/* The open call returns at once; the socket arrives through the poll fd. */
static void slow_dns_test(void)
{
    struct c300x_config config;
    struct c300x_mqtt mqtt;
    uint16_t port;
    int listener = broker(&port);
    config_for(&config, port);
    c300x_mqtt_init(&mqtt);
    atomic_store(&resolve_delay_ms, SLOW_MS);
    long long start = c300x_monotonic_ms();
    c300x_mqtt_open_if_needed(&mqtt, &config, 1, 1000);
    /* Returned before the answer could be there. */
    assert(c300x_monotonic_ms() - start < SLOW_MS - 100);
    int fd = c300x_mqtt_fd(&mqtt);
    assert(fd >= 0 && (c300x_mqtt_poll_events(&mqtt) & POLLIN));
    int timeout = c300x_mqtt_poll_timeout_ms(&mqtt, 1000);
    assert(timeout > SLOW_MS && timeout <= DEADLINE_MS);
    struct pollfd wait = {.fd = fd, .events = c300x_mqtt_poll_events(&mqtt)};
    assert(poll(&wait, 1, DEADLINE_MS + 5000) == 1);
    c300x_mqtt_handle_poll(&mqtt, &config, wait.revents, 1000);
    assert(c300x_mqtt_fd(&mqtt) >= 0 && c300x_mqtt_fd(&mqtt) != fd);
    int peer = accept(listener, NULL, NULL);
    assert(peer >= 0);
    unsigned char connect_packet[64];
    struct pollfd out = {.fd = c300x_mqtt_fd(&mqtt), .events = c300x_mqtt_poll_events(&mqtt)};
    if (poll(&out, 1, 0) == 1 && (out.revents & POLLOUT)) {
        c300x_mqtt_handle_poll(&mqtt, &config, out.revents, 1000);
    }
    assert(recv(peer, connect_packet, sizeof(connect_packet), 0) > 0 && connect_packet[0] == 0x10);
    c300x_mqtt_close(&mqtt);
    close(peer);
    close(listener);
}

/* Closing during a resolution neither waits for it nor leaks it. */
static void cancel_test(void)
{
    struct c300x_config config;
    struct c300x_mqtt mqtt;
    config_for(&config, 1);
    c300x_mqtt_init(&mqtt);
    atomic_store(&resolve_delay_ms, SLOW_MS);
    c300x_mqtt_open_if_needed(&mqtt, &config, 1, 1000);
    long long start = c300x_monotonic_ms();
    c300x_mqtt_close(&mqtt);
    /* Did not wait for the answer. */
    assert(c300x_monotonic_ms() - start < SLOW_MS - 100);
    assert(c300x_mqtt_fd(&mqtt) == -1 && c300x_mqtt_poll_events(&mqtt) == 0);
    config.mqtt_enabled = 0;
    c300x_mqtt_open_if_needed(&mqtt, &config, 1, 1000);
    wait_resolvers_gone();
}

/* An attempt that does not end in time is given up and retried later. */
static void deadline_test(void)
{
    struct c300x_config config;
    struct c300x_mqtt mqtt;
    config_for(&config, 1);
    c300x_mqtt_init(&mqtt);
    atomic_store(&resolve_delay_ms, DEADLINE_MS + 1500);
    c300x_mqtt_open_if_needed(&mqtt, &config, 1, 1000);
    assert(c300x_mqtt_fd(&mqtt) >= 0);
    usleep((DEADLINE_MS + 200) * 1000);
    c300x_mqtt_tick(&mqtt, &config, 1001);
    assert(c300x_mqtt_fd(&mqtt) == -1);
    assert(mqtt.next_connect_at == 1005);
    c300x_mqtt_open_if_needed(&mqtt, &config, 1, 1001);
    assert(c300x_mqtt_fd(&mqtt) == -1);
    wait_resolvers_gone();
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    alarm(60);
    if (strcmp(argv[1], "slow_dns") == 0) {
        slow_dns_test();
    } else if (strcmp(argv[1], "cancel") == 0) {
        cancel_test();
    } else if (strcmp(argv[1], "deadline") == 0) {
        deadline_test();
    } else {
        return 2;
    }
    return 0;
}
