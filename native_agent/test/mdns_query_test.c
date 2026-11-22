#include <assert.h>
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

static void check_identity(void)
{
    struct c300x_config config = {.api_port = 8091};
    unsigned char packet[2048];
    char before[64], after[64], label[64];
    c300x_mdns_device_id(before, sizeof(before));
    for (int c100x = 0; c100x <= 1; c100x++) {
        model = c100x ? C300X_DEVICE_MODEL_C100X : C300X_DEVICE_MODEL_C300X;
        strcpy(config.mdns_name, "BTicino C300X");
        int size = mdns_build_response(&config, packet, sizeof(packet), 120);
        assert(size > 0);
        assert(contains(packet, size, c100x ? "model=C100X" : "model=C300X"));
        assert(contains(packet, size, c100x ? "name=BTicino C100X" : "name=BTicino C300X"));
        assert(contains(packet, size, "_bticino-c300x-agent"));
        c300x_mdns_device_id(after, sizeof(after));
        assert(strcmp(before, after) == 0);
        mdns_instance_name(&config, "c300x-001122334455", label, sizeof(label));
        assert(strcmp(label, c100x ? "BTicino C100X 334455" : "BTicino C300X 334455") == 0);
        strcpy(config.mdns_name, "Front door");
        size = mdns_build_response(&config, packet, sizeof(packet), 120);
        assert(size > 0 && contains(packet, size, "name=Front door"));
        mdns_instance_name(&config, "c300x-001122334455", label, sizeof(label));
        assert(strcmp(label, "Front door 334455") == 0);
    }
}

int main(void)
{
    check_identity();
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
