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
#define getifaddrs test_getifaddrs
#define freeifaddrs test_freeifaddrs
#include "../src/mdns.c"

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

int main(void)
{
    test_address_change_reopens_socket();
    struct c300x_config config = {0};
    unsigned char packet[512] = {0};
    size_t size = 12;
    packet[5] = 1;
    assert(mdns_put_name(packet, sizeof(packet), &size, C300X_MDNS_SERVICE));
    assert(mdns_put_u16(packet, sizeof(packet), &size, 12));
    assert(mdns_put_u16(packet, sizeof(packet), &size, 1));
    assert(mdns_relevant_query(packet, size, &config));
    packet[2] = 0x84;
    assert(!mdns_relevant_query(packet, size, &config));
    packet[2] = 0;
    assert(!mdns_relevant_query(packet, size - 1, &config));
    packet[5] = 2;
    packet[size++] = 0xc0;
    packet[size++] = 12;
    assert(mdns_put_u16(packet, sizeof(packet), &size, 12));
    assert(mdns_put_u16(packet, sizeof(packet), &size, 1));
    assert(mdns_relevant_query(packet, size, &config));
    packet[12] = 0xc0;
    packet[13] = 12;
    assert(!mdns_relevant_query(packet, size, &config));
    size = 12;
    packet[5] = 1;
    assert(mdns_put_name(packet, sizeof(packet), &size, "_other._tcp.local"));
    assert(mdns_put_u16(packet, sizeof(packet), &size, 12));
    assert(mdns_put_u16(packet, sizeof(packet), &size, 1));
    assert(!mdns_relevant_query(packet, size, &config));
    assert(!mdns_relevant_query(packet, 0, &config));
    return 0;
}
