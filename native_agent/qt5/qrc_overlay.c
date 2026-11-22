/*
 * Loaded with LD_PRELOAD into the display program of firmware 3.0.x, whose
 * display files are Qt resources inside the program. Before the program
 * registers its own resources, this registers the resource file the agent
 * built; Qt takes a file found in several resources from the first one
 * registered, so the pages of the integration replace the vendor ones. Without
 * a usable file it does nothing and the display runs as shipped.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define OVERLAY_PATH "/home/bticino/cfg/extra/c300x-native-agent/display-qt5.rcc"
#define OVERLAY_MAX_BYTES (16L * 1024L * 1024L)
#define HEADER_BYTES 20
#define NODE_BYTES 22u
#define MAX_NODES 256u

/* bool qRegisterResourceData(int, const uchar *, const uchar *, const uchar *) */
#define REGISTER_SYMBOL "_Z21qRegisterResourceDataiPKhS0_S0_"

typedef unsigned char (*register_fn)(int, const unsigned char *, const unsigned char *, const unsigned char *);
_Static_assert(sizeof(void *) == sizeof(register_fn), "dlsym result must fit a function pointer");

static uint32_t read_be32(const unsigned char *bytes)
{
    return ((uint32_t)bytes[0] << 24) | ((uint32_t)bytes[1] << 16) | ((uint32_t)bytes[2] << 8) | bytes[3];
}

static uint32_t read_be16(const unsigned char *bytes)
{
    return ((uint32_t)bytes[0] << 8) | bytes[1];
}

/* qRegisterResourceData receives pointers, not lengths: Qt trusts all child,
 * name and data offsets. Accept only the uncompressed v2 layout our packer
 * emits, with disjoint tables and a bounded, forward-only tree. */
static int valid_overlay(const unsigned char *rcc, size_t size)
{
    uint32_t tree = read_be32(rcc + 8), data = read_be32(rcc + 12), names = read_be32(rcc + 16);
    uint32_t count, next_child = 1;
    if (memcmp(rcc, "qres", 4) != 0 || read_be32(rcc + 4) != 2
        || tree != HEADER_BYTES || names <= tree || data <= names || data >= size
        || (names - tree) % NODE_BYTES != 0) return 0;
    count = (names - tree) / NODE_BYTES;
    if (count < 2 || count > MAX_NODES) return 0;
    for (uint32_t i = 0; i < count; i++) {
        const unsigned char *node = rcc + tree + i * NODE_BYTES;
        uint32_t flags = read_be16(node + 4);
        if (i > 0) {
            uint32_t offset = read_be32(node), length, hash = 0;
            const unsigned char *name;
            if (data - names < 6 || offset > data - names - 6) return 0;
            name = rcc + names + offset;
            length = read_be16(name);
            if (length == 0 || length > (data - names - offset - 6) / 2) return 0;
            for (uint32_t n = 0; n < length; n++) {
                uint32_t ch = read_be16(name + 6 + n * 2);
                if (ch == 0 || ch == '/') return 0;
                hash = (hash << 4) + ch;
                hash ^= (hash & 0xf0000000u) >> 23;
                hash &= 0x0fffffffu;
            }
            if (hash != read_be32(name + 2)) return 0;
        } else if (flags != 2) return 0;
        if (flags == 2) {
            uint32_t children = read_be32(node + 6), first = read_be32(node + 10);
            if (children == 0 || first != next_child || first <= i || children > count - first) return 0;
            next_child += children;
        } else if (flags == 0) {
            uint32_t offset = read_be32(node + 10);
            if (size - data < 4 || offset > size - data - 4
                || read_be32(rcc + data + offset) > size - data - offset - 4) return 0;
        } else return 0;
    }
    return next_child == count;
}

static void reject_overlay(const char *path)
{
    char failed[4096];
    int length = snprintf(failed, sizeof(failed), "%s.failed", path);
    if (length > 0 && (size_t)length < sizeof(failed)) {
        int fd = open(failed, O_WRONLY | O_CREAT | O_CLOEXEC | O_NOFOLLOW, 0600);
        if (fd >= 0) close(fd);
    }
    fputs("c300x-qrc-overlay: invalid resource file; using stock resources\n", stderr);
}

static const unsigned char *map_overlay(const char *path, size_t *size)
{
    struct stat info;
    void *map;
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);

    if (fd < 0) {
        return NULL;
    }
    if (fstat(fd, &info) != 0 || !S_ISREG(info.st_mode) || info.st_size < HEADER_BYTES
        || info.st_size > OVERLAY_MAX_BYTES) {
        close(fd);
        return NULL;
    }
    map = mmap(NULL, (size_t)info.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (map == MAP_FAILED) {
        return NULL;
    }
    *size = (size_t)info.st_size;
    return map;
}

__attribute__((constructor)) static void c300x_qrc_overlay(void)
{
    const char *path = getenv("C300X_QRC_OVERLAY");
    const unsigned char *rcc;
    size_t size = 0;
    uint32_t version;
    uint32_t tree;
    uint32_t data;
    uint32_t names;
    register_fn register_resource;
    void *symbol;

    symbol = dlsym(RTLD_DEFAULT, REGISTER_SYMBOL);
    if (symbol == NULL) {
        /* Not the display program: a helper that starts it passes this on. */
        return;
    }
    /* Programs the display program starts must not load this again. */
    unsetenv("LD_PRELOAD");
    memcpy(&register_resource, &symbol, sizeof(register_resource));
    path = path != NULL && path[0] != '\0' ? path : OVERLAY_PATH;
    rcc = map_overlay(path, &size);
    if (rcc == NULL) {
        reject_overlay(path);
        return;
    }
    version = read_be32(rcc + 4);
    tree = read_be32(rcc + 8);
    data = read_be32(rcc + 12);
    names = read_be32(rcc + 16);
    if (
        !valid_overlay(rcc, size)
        || !register_resource((int)version, rcc + tree, rcc + names, rcc + data)
    ) {
        reject_overlay(path);
        munmap((void *)rcc, size);
    }
    /* A registered file stays mapped for the life of the program. */
}
