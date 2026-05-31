#include "mdns.h"

#include <arpa/inet.h>
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <ifaddrs.h>
#include <limits.h>
#include <net/if.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define C300X_MDNS_GROUP "224.0.0.251"
#define C300X_MDNS_PORT 5353
#define C300X_MDNS_ENUMERATION "_services._dns-sd._udp.local"
#define C300X_MDNS_SERVICE "_bticino-c300x-agent._tcp.local"
#define C300X_MDNS_ANNOUNCE_SECONDS 60
#define C300X_MDNS_CLASS_IN 0x0001
#define C300X_MDNS_CLASS_FLUSH_IN 0x8001
#define C300X_MDNS_FALLBACK_ID "c300x-agent"

static int mdns_open_socket(void);
static void mdns_send_response(
    struct c300x_mdns *mdns,
    const struct c300x_config *config,
    uint32_t ttl
);
static int mdns_build_response(
    const struct c300x_config *config,
    unsigned char *buffer,
    size_t buffer_len,
    uint32_t ttl
);
static int mdns_put_u16(
    unsigned char *buffer,
    size_t buffer_len,
    size_t *offset,
    uint16_t value
);
static int mdns_put_u32(
    unsigned char *buffer,
    size_t buffer_len,
    size_t *offset,
    uint32_t value
);
static int mdns_put_name(
    unsigned char *buffer,
    size_t buffer_len,
    size_t *offset,
    const char *name
);
static int mdns_put_record_header(
    unsigned char *buffer,
    size_t buffer_len,
    size_t *offset,
    const char *name,
    uint16_t type,
    uint16_t record_class,
    uint32_t ttl,
    uint16_t rdlength
);
static int mdns_put_txt_item(
    unsigned char *buffer,
    size_t buffer_len,
    size_t *offset,
    const char *value
);
static void mdns_instance_name(
    const struct c300x_config *config,
    const char *device_id,
    char *out,
    size_t out_len
);
static int mdns_read_mac_suffix(char *out, size_t out_len);
static int mdns_normalize_mac(const char *raw, char *out, size_t out_len);
static void mdns_sanitize_label(const char *source, char *out, size_t out_len);
static struct in_addr mdns_local_ipv4(void);
static int mdns_local_ipv6(struct in6_addr *result);
static void mdns_set_fd_cloexec(int fd);
static void mdns_set_fd_nonblocking(int fd);

void c300x_mdns_init(struct c300x_mdns *mdns)
{
    mdns->fd = -1;
    mdns->next_announce_at = 0;
    mdns->announced = 0;
}

void c300x_mdns_close(struct c300x_mdns *mdns)
{
    if (mdns->fd >= 0) {
        close(mdns->fd);
        mdns->fd = -1;
    }
    mdns->announced = 0;
}

void c300x_mdns_open_if_needed(
    struct c300x_mdns *mdns,
    const struct c300x_config *config,
    int home_assistant_connected,
    int network_online,
    time_t now
)
{
    if (!config->mdns_enabled || home_assistant_connected || !network_online) {
        c300x_mdns_close(mdns);
        return;
    }
    if (mdns->fd >= 0 || mdns->next_announce_at > now) {
        return;
    }
    mdns->fd = mdns_open_socket();
    if (mdns->fd < 0) {
        mdns->next_announce_at = now + C300X_MDNS_ANNOUNCE_SECONDS;
        return;
    }
    mdns->announced = 0;
    mdns->next_announce_at = now;
}

int c300x_mdns_fd(const struct c300x_mdns *mdns)
{
    return mdns->fd;
}

time_t c300x_mdns_next_announce_at(const struct c300x_mdns *mdns)
{
    return mdns->next_announce_at;
}

void c300x_mdns_handle_query(
    struct c300x_mdns *mdns,
    const struct c300x_config *config
)
{
    unsigned char buffer[512];

    while (mdns->fd >= 0) {
        ssize_t read_size = recv(mdns->fd, buffer, sizeof(buffer), 0);
        if (read_size < 0 && errno == EINTR) {
            continue;
        }
        if (read_size <= 0) {
            break;
        }
        mdns_send_response(mdns, config, 120);
    }
}

void c300x_mdns_announce_if_due(
    struct c300x_mdns *mdns,
    const struct c300x_config *config,
    time_t now
)
{
    if (mdns->fd < 0 || mdns->next_announce_at > now) {
        return;
    }
    mdns_send_response(mdns, config, 120);
    mdns->announced = 1;
    mdns->next_announce_at = now + C300X_MDNS_ANNOUNCE_SECONDS;
}

static int mdns_open_socket(void)
{
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in bind_addr;
    struct ip_mreq membership;
    struct in_addr local_address;
    unsigned char ttl = 255;
    unsigned char loop = 0;
    int reuse = 1;

    if (fd < 0) {
        return -1;
    }
    (void)setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
#ifdef SO_REUSEPORT
    (void)setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &reuse, sizeof(reuse));
#endif
    mdns_set_fd_cloexec(fd);
    memset(&bind_addr, 0, sizeof(bind_addr));
    bind_addr.sin_family = AF_INET;
    bind_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    bind_addr.sin_port = htons(C300X_MDNS_PORT);
    if (bind(fd, (struct sockaddr *)&bind_addr, sizeof(bind_addr)) != 0) {
        close(fd);
        return -1;
    }
    local_address = mdns_local_ipv4();
    if (local_address.s_addr == htonl(INADDR_LOOPBACK)) {
        close(fd);
        return -1;
    }
    memset(&membership, 0, sizeof(membership));
    if (inet_pton(AF_INET, C300X_MDNS_GROUP, &membership.imr_multiaddr) != 1) {
        close(fd);
        return -1;
    }
    membership.imr_interface = local_address;
    if (setsockopt(fd, IPPROTO_IP, IP_ADD_MEMBERSHIP, &membership, sizeof(membership)) != 0) {
        close(fd);
        return -1;
    }
    (void)setsockopt(
        fd,
        IPPROTO_IP,
        IP_MULTICAST_IF,
        &local_address,
        sizeof(local_address)
    );
    (void)setsockopt(fd, IPPROTO_IP, IP_MULTICAST_TTL, &ttl, sizeof(ttl));
    (void)setsockopt(fd, IPPROTO_IP, IP_MULTICAST_LOOP, &loop, sizeof(loop));
    mdns_set_fd_nonblocking(fd);
    return fd;
}

static void mdns_send_response(
    struct c300x_mdns *mdns,
    const struct c300x_config *config,
    uint32_t ttl
)
{
    unsigned char buffer[1024];
    struct sockaddr_in target;
    int length = mdns_build_response(config, buffer, sizeof(buffer), ttl);

    if (mdns->fd < 0 || length <= 0) {
        return;
    }
    memset(&target, 0, sizeof(target));
    target.sin_family = AF_INET;
    target.sin_port = htons(C300X_MDNS_PORT);
    if (inet_pton(AF_INET, C300X_MDNS_GROUP, &target.sin_addr) != 1) {
        return;
    }
    (void)sendto(
        mdns->fd,
        buffer,
        (size_t)length,
        MSG_NOSIGNAL,
        (struct sockaddr *)&target,
        sizeof(target)
    );
}

static int mdns_build_response(
    const struct c300x_config *config,
    unsigned char *buffer,
    size_t buffer_len,
    uint32_t ttl
)
{
    char instance_label[64];
    char instance_name[160];
    char device_id[64];
    char host_name[80];
    char txt_id[80];
    char txt_name[80];
    char txt_version[80];
    unsigned char rdata[512];
    struct in_addr address = mdns_local_ipv4();
    struct in6_addr ipv6_address;
    int has_ipv6 = mdns_local_ipv6(&ipv6_address);
    size_t offset = 0;
    size_t rdata_len = 0;

    c300x_mdns_device_id(device_id, sizeof(device_id));
    mdns_instance_name(config, device_id, instance_label, sizeof(instance_label));
    if (
        snprintf(
            instance_name,
            sizeof(instance_name),
            "%s.%s",
            instance_label,
            C300X_MDNS_SERVICE
        ) >= (int)sizeof(instance_name)
    ) {
        return 0;
    }
    if (
        snprintf(
            host_name,
            sizeof(host_name),
            "%s.local",
            device_id
        ) >= (int)sizeof(host_name)
    ) {
        return 0;
    }
    if (
        snprintf(
            txt_id,
            sizeof(txt_id),
            "id=%s",
            device_id
        ) >= (int)sizeof(txt_id)
    ) {
        return 0;
    }
    if (
        snprintf(
            txt_name,
            sizeof(txt_name),
            "name=%s",
            config->mdns_name[0] != '\0' ? config->mdns_name : "BTicino C300X"
        ) >= (int)sizeof(txt_name)
    ) {
        return 0;
    }
    if (
        snprintf(
            txt_version,
            sizeof(txt_version),
            "version=%s",
            C300X_NATIVE_AGENT_VERSION
        ) >= (int)sizeof(txt_version)
    ) {
        return 0;
    }

    if (
        !mdns_put_u16(buffer, buffer_len, &offset, 0)
        || !mdns_put_u16(buffer, buffer_len, &offset, 0x8400)
        || !mdns_put_u16(buffer, buffer_len, &offset, 0)
        || !mdns_put_u16(buffer, buffer_len, &offset, 2)
        || !mdns_put_u16(buffer, buffer_len, &offset, 0)
        || !mdns_put_u16(buffer, buffer_len, &offset, (uint16_t)(3 + (has_ipv6 ? 1 : 0)))
    ) {
        return 0;
    }

    rdata_len = 0;
    if (!mdns_put_name(rdata, sizeof(rdata), &rdata_len, C300X_MDNS_SERVICE)) {
        return 0;
    }
    if (
        !mdns_put_record_header(
            buffer,
            buffer_len,
            &offset,
            C300X_MDNS_ENUMERATION,
            12,
            C300X_MDNS_CLASS_IN,
            ttl,
            (uint16_t)rdata_len
        )
        || offset + rdata_len > buffer_len
    ) {
        return 0;
    }
    memcpy(buffer + offset, rdata, rdata_len);
    offset += rdata_len;

    rdata_len = 0;
    if (!mdns_put_name(rdata, sizeof(rdata), &rdata_len, instance_name)) {
        return 0;
    }
    if (
        !mdns_put_record_header(
            buffer,
            buffer_len,
            &offset,
            C300X_MDNS_SERVICE,
            12,
            C300X_MDNS_CLASS_IN,
            ttl,
            (uint16_t)rdata_len
        )
        || offset + rdata_len > buffer_len
    ) {
        return 0;
    }
    memcpy(buffer + offset, rdata, rdata_len);
    offset += rdata_len;

    rdata_len = 0;
    if (
        !mdns_put_u16(rdata, sizeof(rdata), &rdata_len, 0)
        || !mdns_put_u16(rdata, sizeof(rdata), &rdata_len, 0)
        || !mdns_put_u16(rdata, sizeof(rdata), &rdata_len, config->api_port)
        || !mdns_put_name(rdata, sizeof(rdata), &rdata_len, host_name)
    ) {
        return 0;
    }
    if (
        !mdns_put_record_header(
            buffer,
            buffer_len,
            &offset,
            instance_name,
            33,
            C300X_MDNS_CLASS_FLUSH_IN,
            ttl,
            (uint16_t)rdata_len
        )
        || offset + rdata_len > buffer_len
    ) {
        return 0;
    }
    memcpy(buffer + offset, rdata, rdata_len);
    offset += rdata_len;

    rdata_len = 0;
    if (
        !mdns_put_txt_item(rdata, sizeof(rdata), &rdata_len, "api=v1")
        || !mdns_put_txt_item(rdata, sizeof(rdata), &rdata_len, "path=/api/v1")
        || !mdns_put_txt_item(rdata, sizeof(rdata), &rdata_len, txt_id)
        || !mdns_put_txt_item(rdata, sizeof(rdata), &rdata_len, txt_name)
        || !mdns_put_txt_item(rdata, sizeof(rdata), &rdata_len, txt_version)
        || !mdns_put_txt_item(rdata, sizeof(rdata), &rdata_len, "model=C300X")
    ) {
        return 0;
    }
    if (
        !mdns_put_record_header(
            buffer,
            buffer_len,
            &offset,
            instance_name,
            16,
            C300X_MDNS_CLASS_FLUSH_IN,
            ttl,
            (uint16_t)rdata_len
        )
        || offset + rdata_len > buffer_len
    ) {
        return 0;
    }
    memcpy(buffer + offset, rdata, rdata_len);
    offset += rdata_len;

    rdata_len = 0;
    memcpy(rdata + rdata_len, &address.s_addr, sizeof(address.s_addr));
    rdata_len += sizeof(address.s_addr);
    if (
        !mdns_put_record_header(
            buffer,
            buffer_len,
            &offset,
            host_name,
            1,
            C300X_MDNS_CLASS_FLUSH_IN,
            ttl,
            (uint16_t)rdata_len
        )
        || offset + rdata_len > buffer_len
    ) {
        return 0;
    }
    memcpy(buffer + offset, rdata, rdata_len);
    offset += rdata_len;

    if (has_ipv6) {
        rdata_len = 0;
        memcpy(rdata + rdata_len, ipv6_address.s6_addr, sizeof(ipv6_address.s6_addr));
        rdata_len += sizeof(ipv6_address.s6_addr);
        if (
            !mdns_put_record_header(
                buffer,
                buffer_len,
                &offset,
                host_name,
                28,
                C300X_MDNS_CLASS_FLUSH_IN,
                ttl,
                (uint16_t)rdata_len
            )
            || offset + rdata_len > buffer_len
        ) {
            return 0;
        }
        memcpy(buffer + offset, rdata, rdata_len);
        offset += rdata_len;
    }

    if (offset > (size_t)INT_MAX) {
        return 0;
    }
    return (int)offset;
}

static int mdns_put_u16(
    unsigned char *buffer,
    size_t buffer_len,
    size_t *offset,
    uint16_t value
)
{
    if (*offset + 2 > buffer_len) {
        return 0;
    }
    buffer[(*offset)++] = (unsigned char)((value >> 8) & 0xff);
    buffer[(*offset)++] = (unsigned char)(value & 0xff);
    return 1;
}

static int mdns_put_u32(
    unsigned char *buffer,
    size_t buffer_len,
    size_t *offset,
    uint32_t value
)
{
    if (*offset + 4 > buffer_len) {
        return 0;
    }
    buffer[(*offset)++] = (unsigned char)((value >> 24) & 0xff);
    buffer[(*offset)++] = (unsigned char)((value >> 16) & 0xff);
    buffer[(*offset)++] = (unsigned char)((value >> 8) & 0xff);
    buffer[(*offset)++] = (unsigned char)(value & 0xff);
    return 1;
}

static int mdns_put_name(
    unsigned char *buffer,
    size_t buffer_len,
    size_t *offset,
    const char *name
)
{
    const char *label = name;
    const char *ptr = name;

    while (*ptr != '\0') {
        if (*ptr == '.') {
            size_t label_len = (size_t)(ptr - label);
            if (label_len > 63 || *offset + label_len + 1 > buffer_len) {
                return 0;
            }
            buffer[(*offset)++] = (unsigned char)label_len;
            memcpy(buffer + *offset, label, label_len);
            *offset += label_len;
            label = ptr + 1;
        }
        ptr++;
    }
    if (ptr != label) {
        size_t label_len = (size_t)(ptr - label);
        if (label_len > 63 || *offset + label_len + 1 > buffer_len) {
            return 0;
        }
        buffer[(*offset)++] = (unsigned char)label_len;
        memcpy(buffer + *offset, label, label_len);
        *offset += label_len;
    }
    if (*offset + 1 > buffer_len) {
        return 0;
    }
    buffer[(*offset)++] = 0;
    return 1;
}

static int mdns_put_record_header(
    unsigned char *buffer,
    size_t buffer_len,
    size_t *offset,
    const char *name,
    uint16_t type,
    uint16_t record_class,
    uint32_t ttl,
    uint16_t rdlength
)
{
    return mdns_put_name(buffer, buffer_len, offset, name)
        && mdns_put_u16(buffer, buffer_len, offset, type)
        && mdns_put_u16(buffer, buffer_len, offset, record_class)
        && mdns_put_u32(buffer, buffer_len, offset, ttl)
        && mdns_put_u16(buffer, buffer_len, offset, rdlength);
}

static int mdns_put_txt_item(
    unsigned char *buffer,
    size_t buffer_len,
    size_t *offset,
    const char *value
)
{
    size_t value_len = strlen(value);
    if (value_len > 255 || *offset + value_len + 1 > buffer_len) {
        return 0;
    }
    buffer[(*offset)++] = (unsigned char)value_len;
    memcpy(buffer + *offset, value, value_len);
    *offset += value_len;
    return 1;
}

static void mdns_instance_name(
    const struct c300x_config *config,
    const char *device_id,
    char *out,
    size_t out_len
)
{
    char base[48];
    const char *suffix = device_id;
    const char *source = config->mdns_name[0] != '\0' ? config->mdns_name : "BTicino C300X";

    if (out_len == 0) {
        return;
    }
    mdns_sanitize_label(source, base, sizeof(base));
    if (base[0] == '\0') {
        snprintf(base, sizeof(base), "%s", "BTicino C300X");
    }
    if (strncmp(device_id, "c300x-", 6) == 0 && strlen(device_id) > 6) {
        suffix = device_id + strlen(device_id) - 6;
    }
    if (suffix[0] != '\0') {
        snprintf(out, out_len, "%s %s", base, suffix);
        return;
    }
    snprintf(out, out_len, "%s", base);
}

void c300x_mdns_device_id(char *out, size_t out_len)
{
    char suffix[32];
    char host[64];
    char clean_host[48];

    if (out_len == 0) {
        return;
    }
    if (mdns_read_mac_suffix(suffix, sizeof(suffix))) {
        snprintf(out, out_len, "c300x-%s", suffix);
        return;
    }
    if (gethostname(host, sizeof(host)) == 0) {
        host[sizeof(host) - 1] = '\0';
        mdns_sanitize_label(host, clean_host, sizeof(clean_host));
        if (clean_host[0] != '\0') {
            snprintf(out, out_len, "c300x-%s", clean_host);
            return;
        }
    }
    snprintf(out, out_len, "%s", C300X_MDNS_FALLBACK_ID);
}

static int mdns_read_mac_suffix(char *out, size_t out_len)
{
    DIR *dir;
    struct dirent *entry;

    if (out_len < 13) {
        return 0;
    }
    dir = opendir("/sys/class/net");
    if (dir == NULL) {
        return 0;
    }
    while ((entry = readdir(dir)) != NULL) {
        char path[PATH_MAX];
        char raw[64];
        FILE *file;
        int ok;

        if (
            strcmp(entry->d_name, ".") == 0
            || strcmp(entry->d_name, "..") == 0
            || strcmp(entry->d_name, "lo") == 0
        ) {
            continue;
        }
        if (
            snprintf(path, sizeof(path), "/sys/class/net/%s/address", entry->d_name)
            >= (int)sizeof(path)
        ) {
            continue;
        }
        file = fopen(path, "r");
        if (file == NULL) {
            continue;
        }
        raw[0] = '\0';
        if (fgets(raw, sizeof(raw), file) == NULL) {
            fclose(file);
            continue;
        }
        fclose(file);
        ok = mdns_normalize_mac(raw, out, out_len);
        if (ok) {
            closedir(dir);
            return 1;
        }
    }
    closedir(dir);
    return 0;
}

static int mdns_normalize_mac(const char *raw, char *out, size_t out_len)
{
    size_t written = 0;
    int has_non_zero = 0;

    if (out_len < 13) {
        return 0;
    }
    for (size_t index = 0; raw[index] != '\0' && written < 12; index++) {
        unsigned char ch = (unsigned char)raw[index];
        if (!isxdigit(ch)) {
            continue;
        }
        ch = (unsigned char)tolower(ch);
        if (ch != '0') {
            has_non_zero = 1;
        }
        out[written++] = (char)ch;
    }
    if (written != 12 || !has_non_zero) {
        out[0] = '\0';
        return 0;
    }
    out[written] = '\0';
    return 1;
}

static void mdns_sanitize_label(const char *source, char *out, size_t out_len)
{
    size_t written = 0;

    if (out_len == 0) {
        return;
    }
    for (size_t index = 0; source[index] != '\0' && written + 1 < out_len; index++) {
        unsigned char ch = (unsigned char)source[index];
        if (ch == '.' || ch < 32 || ch >= 127) {
            ch = '-';
        }
        out[written++] = (char)ch;
    }
    out[written] = '\0';
}

static struct in_addr mdns_local_ipv4(void)
{
    struct in_addr result;
    struct ifaddrs *ifaddr = NULL;

    result.s_addr = htonl(INADDR_LOOPBACK);
    if (getifaddrs(&ifaddr) != 0) {
        return result;
    }
    for (struct ifaddrs *item = ifaddr; item != NULL; item = item->ifa_next) {
        struct sockaddr_in *addr;
        uint32_t ipv4;
        if (
            item->ifa_addr == NULL
            || item->ifa_addr->sa_family != AF_INET
            || (item->ifa_flags & IFF_UP) == 0
            || (item->ifa_flags & IFF_LOOPBACK) != 0
        ) {
            continue;
        }
        addr = (struct sockaddr_in *)item->ifa_addr;
        ipv4 = ntohl(addr->sin_addr.s_addr);
        if (ipv4 == 0 || (ipv4 & 0xff000000U) == 0x7f000000U || (ipv4 & 0xffff0000U) == 0xa9fe0000U) {
            continue;
        }
        result = addr->sin_addr;
        break;
    }
    freeifaddrs(ifaddr);
    return result;
}

static int mdns_local_ipv6(struct in6_addr *result)
{
    struct ifaddrs *ifaddr = NULL;

    if (result == NULL) {
        return 0;
    }
    memset(result, 0, sizeof(*result));
    if (getifaddrs(&ifaddr) != 0) {
        return 0;
    }
    for (struct ifaddrs *item = ifaddr; item != NULL; item = item->ifa_next) {
        struct sockaddr_in6 *addr;
        if (
            item->ifa_addr == NULL
            || item->ifa_addr->sa_family != AF_INET6
            || (item->ifa_flags & IFF_UP) == 0
            || (item->ifa_flags & IFF_LOOPBACK) != 0
        ) {
            continue;
        }
        addr = (struct sockaddr_in6 *)item->ifa_addr;
        if (
            IN6_IS_ADDR_UNSPECIFIED(&addr->sin6_addr)
            || IN6_IS_ADDR_LOOPBACK(&addr->sin6_addr)
            || IN6_IS_ADDR_MULTICAST(&addr->sin6_addr)
            || IN6_IS_ADDR_LINKLOCAL(&addr->sin6_addr)
        ) {
            continue;
        }
        *result = addr->sin6_addr;
        freeifaddrs(ifaddr);
        return 1;
    }
    freeifaddrs(ifaddr);
    return 0;
}

static void mdns_set_fd_nonblocking(int fd)
{
    int enabled = 1;

    (void)ioctl(fd, FIONBIO, &enabled);
}

static void mdns_set_fd_cloexec(int fd)
{
    (void)ioctl(fd, FIOCLEX);
}
