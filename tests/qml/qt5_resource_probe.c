/* Offline ARM probe of the original firmware QtCore, without the vendor GUI.
 * No development headers are available. Use exported ABI entry points and
 * oversized aligned storage, as in qt4_runtime_probe.c. Never install this.
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void *symbol(void *library, const char *name)
{
    void *value = dlsym(library, name);
    if (value == NULL) { fprintf(stderr, "%s: %s\n", name, dlerror()); exit(2); }
    return value;
}

int main(int argc, char **argv)
{
    extern char **environ;
    environ = argv + argc + 1;
    setbuf(stdout, NULL);
    if (argc != 3 && argc != 4) return 2;
    void *core = dlopen("libQt5Core.so.5", RTLD_NOW | RTLD_GLOBAL);
    if (core == NULL) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    printf("FIRMWARE_QT_VERSION=%s\n", ((const char *(*)(void))symbol(core, "qVersion"))());
    if (dlopen(argv[1], RTLD_NOW | RTLD_GLOBAL) == NULL) {
        fprintf(stderr, "%s\n", dlerror()); return 2;
    }
    if (argc == 4) {
        /* Pinned 3.0.6 resource tables, checked by the Python test's hash.
         * Register data only, never load or execute the vendor program. */
        FILE *file = fopen(argv[3], "rb");
        unsigned char *vendor = malloc(2799088);
        if (file == NULL || vendor == NULL || fread(vendor, 1, 2799088, file) != 2799088) return 2;
        fclose(file);
        int ok = ((int (*)(int, const void *, const void *, const void *))
            symbol(core, "_Z21qRegisterResourceDataiPKhS0_S0_"))(2, vendor + 0x35c6c, vendor + 0x3672c, vendor + 0x3791c);
        printf("VENDOR_RESOURCES_REGISTERED=%d\n", ok);
    }
    void *path = calloc(1, 65536), *locale = calloc(1, 65536), *resource = calloc(1, 65536);
    if (path == NULL || locale == NULL || resource == NULL) return 2;
    ((void (*)(void *, const char *, int))symbol(core, "_ZN7QString15fromUtf8_helperEPKci"))(path, argv[2], (int)strlen(argv[2]));
    ((void (*)(void *))symbol(core, "_ZN7QLocaleC1Ev"))(locale);
    ((void (*)(void *, void *, void *))symbol(core, "_ZN9QResourceC1ERK7QStringRK7QLocale"))(resource, path, locale);
    int valid = ((int (*)(void *))symbol(core, "_ZNK9QResource7isValidEv"))(resource);
    printf("RESOURCE_VALID=%d\n", valid);
    if (valid) {
        int64_t size = ((int64_t (*)(void *))symbol(core, "_ZNK9QResource4sizeEv"))(resource);
        const unsigned char *data = ((const unsigned char *(*)(void *))symbol(core, "_ZNK9QResource4dataEv"))(resource);
        if (size <= 0 || size > 16777216 || data == NULL) return 3;
        printf("RESOURCE_BYTES=%lld FIRST=%u LAST=%u\n", (long long)size, data[0], data[size - 1]);
    }
    return 0;
}
