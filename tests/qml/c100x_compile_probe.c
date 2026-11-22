/* ARM compile-only probe for the original C100X Qt 5.10.1 libraries.
 * No Qt headers are available: exported C++ ABI calls use aligned, oversized
 * object storage, as in the other firmware probes. Never call create(),
 * construct QGuiApplication, or start an event loop/vendor application.
 */
#include <dlfcn.h>
#include <link.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void *symbol(void *library, const char *name)
{
    void *value = dlsym(library, name);
    if (value == NULL) {
        fprintf(stderr, "%s: %s\n", name, dlerror());
        exit(2);
    }
    return value;
}

static void *storage(void)
{
    void *value = calloc(1, 65536);
    if (value == NULL) exit(2);
    return value;
}

static int loaded_library(struct dl_phdr_info *info, size_t size, void *data)
{
    (void)size;
    (void)data;
    if (info->dlpi_name[0]) printf("LOADED_LIBRARY=%s\n", info->dlpi_name);
    return 0;
}

int main(int argc, char **argv)
{
    extern char **environ;
    environ = argv + argc + 1;
    setbuf(stdout, NULL);
    if (argc < 3 || argc > 130) return 2;
    void *core = dlopen("libQt5Core.so.5", RTLD_NOW | RTLD_GLOBAL);
    if (core == NULL) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    const char *version = ((const char *(*)(void))symbol(core, "qVersion"))();
    printf("FIRMWARE_QT_VERSION=%s\nMODE=compile-only\n", version);
    if (strcmp(version, "5.10.1") != 0) return 2;
    void *qml = dlopen("libQt5Qml.so.5", RTLD_NOW | RTLD_GLOBAL);
    if (qml == NULL) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    void *app = storage(), *engine = storage(), *path = storage();
    ((void (*)(void *, int *, char **, int))symbol(core, "_ZN16QCoreApplicationC1ERiPPci"))(app, &argc, argv, 0);
    ((void (*)(void *, void *))symbol(qml, "_ZN10QQmlEngineC1EP7QObject"))(engine, NULL);
    ((void (*)(void *, const char *, int))symbol(core, "_ZN7QString15fromUtf8_helperEPKci"))(path, argv[1], (int)strlen(argv[1]));
    ((void (*)(void *, void *))symbol(qml, "_ZN10QQmlEngine13addImportPathERK7QString"))(engine, path);
    /* QString's inline destructor is not exported by this firmware. Retain
     * its small value allocations until this bounded probe process exits. */
    int failures = 0;
    for (int i = 2; i < argc; i++) {
        FILE *file = fopen(argv[i], "rb");
        if (file == NULL || fseek(file, 0, SEEK_END) != 0) return 2;
        long length = ftell(file);
        if (length < 0 || length > 1048576 || fseek(file, 0, SEEK_SET) != 0) return 2;
        char *source = calloc(1, (size_t)length + 1);
        if (source == NULL || fread(source, 1, (size_t)length, file) != (size_t)length) return 2;
        fclose(file);
        void *component = storage(), *url = storage(), *data = storage(), *error = storage();
        ((void (*)(void *, const char *, int))symbol(core, "_ZN7QString15fromUtf8_helperEPKci"))(path, argv[i], (int)strlen(argv[i]));
        ((void (*)(void *, void *))symbol(core, "_ZN4QUrl13fromLocalFileERK7QString"))(url, path);
        ((void (*)(void *, const char *, int))symbol(core, "_ZN10QByteArrayC1EPKci"))(data, source, (int)length);
        ((void (*)(void *, void *, void *))symbol(qml, "_ZN13QQmlComponentC1EP10QQmlEngineP7QObject"))(component, engine, NULL);
        ((void (*)(void *, void *, void *))symbol(qml, "_ZN13QQmlComponent7setDataERK10QByteArrayRK4QUrl"))(component, data, url);
        int status = ((int (*)(void *))symbol(qml, "_ZNK13QQmlComponent6statusEv"))(component);
        printf("COMPILE_STATUS=%d FILE=%s\n", status, argv[i]);
        if (status != 1) {
            failures++;
            ((void (*)(void *, void *))symbol(qml, "_ZNK13QQmlComponent11errorStringEv"))(error, component);
            const uint16_t *text = ((const uint16_t *(*)(void *))symbol(core, "_ZNK7QString5utf16Ev"))(error);
            for (; *text; text++) fputc(*text < 128 ? *text : '?', stderr);
        }
        ((void (*)(void *))symbol(qml, "_ZN13QQmlComponentD1Ev"))(component);
        ((void (*)(void *))symbol(core, "_ZN10QByteArray5clearEv"))(data);
        ((void (*)(void *))symbol(core, "_ZN4QUrlD1Ev"))(url);
        free(component); free(url); free(data); free(error); free(source);
    }
    dl_iterate_phdr(loaded_library, NULL);
    printf("COMPILE_FAILURES=%d\n", failures);
    ((void (*)(void *))symbol(qml, "_ZN10QQmlEngineD1Ev"))(engine);
    ((void (*)(void *))symbol(core, "_ZN16QCoreApplicationD1Ev"))(app);
    free(path); free(engine); free(app);
    return failures ? 1 : 0;
}
