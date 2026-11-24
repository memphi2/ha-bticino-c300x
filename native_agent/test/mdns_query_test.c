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

static enum c300x_device_model model;

enum c300x_device_model c300x_device_model(void)
{
    return model;
}

static int contains(const unsigned char *packet, size_t size, const char *text)
{
    size_t len = strlen(text);
    for (size_t i = 0; i + len <= size; i++) {
        if (memcmp(packet + i, text, len) == 0) return 1;
    }
    return 0;
}

static int service_query(const char *name, const struct c300x_config *config)
{
    unsigned char query[512] = {0};
    size_t size = 12;
    query[5] = 1;
    assert(mdns_put_name(query, sizeof(query), &size, name));
    assert(mdns_put_u16(query, sizeof(query), &size, 12));
    assert(mdns_put_u16(query, sizeof(query), &size, 1));
    return mdns_relevant_query(query, size, config);
}

static void check_identity(void)
{
    struct c300x_config config = {.api_port = 8091};
    unsigned char packet[2048];
    char before[64], after[64], label[64];
    c300x_mdns_device_id(before, sizeof(before));
    for (int c100x = 0; c100x <= 1; c100x++) {
        model = c100x ? C300X_DEVICE_MODEL_C100X : C300X_DEVICE_MODEL_C300X;
        strcpy(config.mdns_name, "BTicino C300X");
        int size = mdns_build_response(&config, "instance-1", packet, sizeof(packet), 120);
        assert(size > 0);
        assert(contains(packet, size, c100x ? "model=C100X" : "model=C300X"));
        assert(contains(packet, size, c100x ? "name=BTicino C100X" : "name=BTicino C300X"));
        assert(contains(packet, size, c100x ? "_bticino-c100x-agent" : "_bticino-c300x-agent"));
        assert(!contains(packet, size, c100x ? "_bticino-c300x-agent" : "_bticino-c100x-agent"));
        assert(service_query("_bticino-c100x-agent._tcp.local", &config) == c100x);
        assert(service_query("_bticino-c300x-agent._tcp.local", &config) == !c100x);
        c300x_mdns_device_id(after, sizeof(after));
        assert(strcmp(before, after) == 0);
        mdns_instance_name(&config, "c300x-001122334455", label, sizeof(label));
        assert(strcmp(label, c100x ? "BTicino C100X 334455" : "BTicino C300X 334455") == 0);
        strcpy(config.mdns_name, "Front door");
        size = mdns_build_response(&config, "instance-1", packet, sizeof(packet), 120);
        assert(size > 0 && contains(packet, size, "name=Front door"));
        mdns_instance_name(&config, "c300x-001122334455", label, sizeof(label));
        assert(strcmp(label, "Front door 334455") == 0);
    }
    model = C300X_DEVICE_MODEL_C300X;
}

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

int main(void)
{
    check_identity();
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
