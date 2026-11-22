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
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define OVERLAY_PATH "/home/bticino/cfg/extra/c300x-native-agent/display-qt5.rcc"
#define OVERLAY_MAX_BYTES (16L * 1024L * 1024L)
#define HEADER_BYTES 20

/* bool qRegisterResourceData(int, const uchar *, const uchar *, const uchar *) */
#define REGISTER_SYMBOL "_Z21qRegisterResourceDataiPKhS0_S0_"

typedef unsigned char (*register_fn)(int, const unsigned char *, const unsigned char *, const unsigned char *);
_Static_assert(sizeof(void *) == sizeof(register_fn), "dlsym result must fit a function pointer");

static uint32_t read_be32(const unsigned char *bytes)
{
    return ((uint32_t)bytes[0] << 24) | ((uint32_t)bytes[1] << 16) | ((uint32_t)bytes[2] << 8) | bytes[3];
}

static const unsigned char *map_overlay(const char *path, size_t *size)
{
    struct stat info;
    void *map;
    int fd = open(path, O_RDONLY | O_CLOEXEC);

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
    rcc = map_overlay(path != NULL && path[0] != '\0' ? path : OVERLAY_PATH, &size);
    if (rcc == NULL) {
        return;
    }
    version = read_be32(rcc + 4);
    tree = read_be32(rcc + 8);
    data = read_be32(rcc + 12);
    names = read_be32(rcc + 16);
    if (
        memcmp(rcc, "qres", 4) != 0 || version < 1 || version > 3
        || tree < HEADER_BYTES || data < HEADER_BYTES || names < HEADER_BYTES
        || tree >= size || data >= size || names >= size
        || !register_resource((int)version, rcc + tree, rcc + names, rcc + data)
    ) {
        munmap((void *)rcc, size);
    }
    /* A registered file stays mapped for the life of the program. */
}
