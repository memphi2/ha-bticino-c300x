#include <assert.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netinet/in.h>
#include <sys/socket.h>

static struct ifaddrs *test_ifaddrs;
static int test_getifaddrs(struct ifaddrs **out)
{
    *out = test_ifaddrs;
    return 0;
}
static void test_freeifaddrs(struct ifaddrs *list)
{
    (void)list;
}
#include <dirent.h>
#include <stddef.h>
#include <string.h>
static int opendir_calls, sendto_calls;
static long long test_clock_ms = 5000;
static DIR *test_opendir(const char *path)
{
    (void)path;
    opendir_calls++;
    return NULL;
}
static ssize_t test_sendto(int fd, const void *data, size_t len, int flags,
                           const struct sockaddr *to, socklen_t to_len)
{
    (void)fd; (void)data; (void)flags; (void)to; (void)to_len;
    sendto_calls++;
    return (ssize_t)len;
}
long long c300x_monotonic_ms(void) { return test_clock_ms; }
#define getifaddrs test_getifaddrs
#define freeifaddrs test_freeifaddrs
#define opendir test_opendir
#define sendto test_sendto
#include "../src/mdns.c"
#undef opendir
#undef sendto
#define TEST_ID "c300x-001122334455"

static void test_address_change_reopens_socket(void)
{
    struct c300x_config config = {0};
    struct c300x_mdns mdns;
    struct sockaddr_in address = {0};
    struct ifaddrs wlan = {0};
    int pair[2];

    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(0xc0a80105U);
    wlan.ifa_name = "wlan0";
    wlan.ifa_flags = IFF_UP;
    wlan.ifa_addr = (struct sockaddr *)&address;
    test_ifaddrs = &wlan;
    /* A local datagram pair: the announcement cannot reach a real network. */
    assert(socketpair(AF_UNIX, SOCK_DGRAM, 0, pair) == 0);
    close(pair[1]);
    c300x_mdns_init(&mdns);
    mdns.fd = pair[0];
    mdns.ipv4 = address.sin_addr.s_addr;
    c300x_mdns_announce_if_due(&mdns, &config, 100);
    assert(mdns.fd == pair[0] && mdns.announced && mdns.next_announce_at == 160);
    address.sin_addr.s_addr = htonl(0xc0a80106U);
    c300x_mdns_announce_if_due(&mdns, &config, 160);
    assert(mdns.fd < 0);
    assert(mdns.next_announce_at == 160);
    test_ifaddrs = NULL;
}

static void test_failed_reopen_schedules_a_retry(void)
{
    struct c300x_config config = {0};
    struct c300x_mdns mdns;

    config.mdns_enabled = 1;
    /* No IPv4 address yet, as between DHCP removing and adding one. */
    test_ifaddrs = NULL;
    c300x_mdns_init(&mdns);
    assert(c300x_mdns_poll_timeout_ms(&mdns, 100) == -1);
    c300x_mdns_open_if_needed(&mdns, &config, 0, 1, 100);
    assert(mdns.fd < 0);
    /* The loop must wake for the retry even without a socket to poll. */
    assert(c300x_mdns_poll_timeout_ms(&mdns, 100) == C300X_MDNS_ANNOUNCE_SECONDS * 1000);
    assert(c300x_mdns_poll_timeout_ms(&mdns, 100 + C300X_MDNS_ANNOUNCE_SECONDS) == 0);
    /* No wake-up while the responder is meant to stay closed. */
    c300x_mdns_open_if_needed(&mdns, &config, 1, 1, 130);
    assert(c300x_mdns_poll_timeout_ms(&mdns, 130) == -1);
    c300x_mdns_open_if_needed(&mdns, &config, 0, 0, 130);
    assert(c300x_mdns_poll_timeout_ms(&mdns, 130) == -1);
}

static void test_home_assistant_presence_expires(void)
{
    const long long quiet = C300X_MDNS_HOME_ASSISTANT_QUIET_MS;

    assert(c300x_mdns_home_assistant_present_ms(0, 1000, 2000) == 0);
    assert(c300x_mdns_home_assistant_present_ms(1, 0, 2000) == 0);
    assert(c300x_mdns_home_assistant_present_ms(1, 1000, 1000) == quiet);
    assert(c300x_mdns_home_assistant_present_ms(1, 1000, 1000 + quiet - 1) == 1);
    assert(c300x_mdns_home_assistant_present_ms(1, 1000, 1000 + quiet) == 0);
    /* HA renews every 300 s: three missed renewals before announcing again. */
    assert(quiet == 900000LL);
}

static size_t service_query(unsigned char *packet, size_t capacity)
{
    size_t size = 12;
    memset(packet, 0, 12);
    packet[5] = 1;
    assert(mdns_put_name(packet, capacity, &size, C300X_MDNS_SERVICE));
    assert(mdns_put_u16(packet, capacity, &size, 12));
    assert(mdns_put_u16(packet, capacity, &size, 1));
    return size;
}

/* A query flood gets one answer per second, and the device id comes from
 * one lookup instead of a /sys scan per datagram. */
static void test_query_flood_is_rate_limited(void)
{
    struct c300x_config config = {0};
    struct c300x_mdns mdns;
    unsigned char packet[512];
    size_t size = service_query(packet, sizeof(packet));
    int pair[2];

    assert(socketpair(AF_UNIX, SOCK_DGRAM, 0, pair) == 0);
    mdns_set_fd_nonblocking(pair[0]);
    c300x_mdns_init(&mdns);
    mdns.fd = pair[0];
    opendir_calls = sendto_calls = 0;
    for (int round = 0; round < 10; round++) {
        for (int i = 0; i < 4; i++) {
            assert(send(pair[1], packet, size, 0) == (ssize_t)size);
        }
        c300x_mdns_handle_query(&mdns, &config);
        test_clock_ms += 100;
    }
    assert(sendto_calls == 1);
    assert(opendir_calls == 1);
    test_clock_ms += 1000;
    assert(send(pair[1], packet, size, 0) == (ssize_t)size);
    c300x_mdns_handle_query(&mdns, &config);
    assert(sendto_calls == 2 && opendir_calls == 1);
    c300x_mdns_close(&mdns);
    close(pair[1]);
}

int main(void)
{
    test_query_flood_is_rate_limited();
    test_address_change_reopens_socket();
    test_failed_reopen_schedules_a_retry();
    test_home_assistant_presence_expires();
    struct c300x_config config = {0};
    unsigned char packet[512] = {0};
    size_t size = 12;
    packet[5] = 1;
    assert(mdns_put_name(packet, sizeof(packet), &size, C300X_MDNS_SERVICE));
    assert(mdns_put_u16(packet, sizeof(packet), &size, 12));
    assert(mdns_put_u16(packet, sizeof(packet), &size, 1));
    assert(mdns_relevant_query(packet, size, &config, TEST_ID));
    packet[2] = 0x84;
    assert(!mdns_relevant_query(packet, size, &config, TEST_ID));
    packet[2] = 0;
    assert(!mdns_relevant_query(packet, size - 1, &config, TEST_ID));
    packet[5] = 2;
    packet[size++] = 0xc0;
    packet[size++] = 12;
    assert(mdns_put_u16(packet, sizeof(packet), &size, 12));
    assert(mdns_put_u16(packet, sizeof(packet), &size, 1));
    assert(mdns_relevant_query(packet, size, &config, TEST_ID));
    packet[12] = 0xc0;
    packet[13] = 12;
    assert(!mdns_relevant_query(packet, size, &config, TEST_ID));
    size = 12;
    packet[5] = 1;
    assert(mdns_put_name(packet, sizeof(packet), &size, "_other._tcp.local"));
    assert(mdns_put_u16(packet, sizeof(packet), &size, 12));
    assert(mdns_put_u16(packet, sizeof(packet), &size, 1));
    assert(!mdns_relevant_query(packet, size, &config, TEST_ID));
    assert(!mdns_relevant_query(packet, 0, &config, TEST_ID));
    return 0;
}
