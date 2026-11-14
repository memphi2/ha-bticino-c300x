#include <assert.h>
#include "../src/mdns.c"

int main(void)
{
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
