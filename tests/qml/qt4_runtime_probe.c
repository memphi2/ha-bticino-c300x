/* Offline Qt 4.8.7 ARM ABI probe, never installed on a device.
 * Firmware development headers are unavailable. Exported methods construct
 * objects in oversized, aligned storage; this is not a general Qt wrapper.
 * Only non-rendering test components are instantiated, without vendor plugins.
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Register built-in QtQuick types without opening a framebuffer. */
int probe_application_type(void) __asm__("_ZN12QApplication4typeEv");
int probe_application_type(void) { return 1; }

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

int main(int argc, char **argv)
{
    extern char **environ;
    environ = argv + argc + 1;
    setbuf(stdout, NULL);
    setbuf(stderr, NULL);
    if (argc != 3) return 2;
    FILE *file = fopen(argv[1], "rb");
    if (file == NULL) return 2;
    if (fseek(file, 0, SEEK_END) != 0) return 2;
    long length = ftell(file);
    if (length < 0 || length > 1048576 || fseek(file, 0, SEEK_SET) != 0) return 2;
    char *source = calloc(1, (size_t)length + 1);
    if (source == NULL || fread(source, 1, (size_t)length, file) != (size_t)length) return 2;
    fclose(file);

    void *core = dlopen("libQtCoreE.so.4", RTLD_NOW | RTLD_GLOBAL);
    if (core == NULL) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    const char *version = ((const char *(*)(void))symbol(core, "_Z8qVersionv"))();
    if (strcmp(version, "4.8.7") != 0) {
        fprintf(stderr, "Unsupported Qt ABI: %s\n", version);
        return 2;
    }
    printf("QT4_RUNTIME_VERSION %s\n", version);
    void *qml = dlopen("libQtDeclarativeE.so.4", RTLD_NOW | RTLD_GLOBAL);
    if (qml == NULL) { fprintf(stderr, "%s\n", dlerror()); return 2; }

    void *app = storage(), *engine = storage(), *component = storage();
    void *path = storage(), *url = storage(), *data = storage(), *error = storage();
    ((void (*)(void *, int *, char **))symbol(core, "_ZN16QCoreApplicationC1ERiPPc"))(app, &argc, argv);
    ((void (*)(void *, void *))symbol(qml, "_ZN18QDeclarativeEngineC1EP7QObject"))(engine, NULL);
    ((void (*)(void *, const char *, int))symbol(core, "_ZN7QString8fromUtf8EPKci"))(path, argv[2], -1);
    ((void (*)(void *, const void *))symbol(qml, "_ZN18QDeclarativeEngine13addImportPathERK7QString"))(engine, path);
    ((void (*)(void *, const char *, int))symbol(core, "_ZN7QString8fromUtf8EPKci"))(path, argv[1], -1);
    ((void (*)(void *, const void *))symbol(core, "_ZN4QUrl13fromLocalFileERK7QString"))(url, path);
    ((void (*)(void *, const char *, int))symbol(core, "_ZN10QByteArrayC1EPKci"))(data, source, (int)length);
    ((void (*)(void *, void *, void *))symbol(qml, "_ZN21QDeclarativeComponentC1EP18QDeclarativeEngineP7QObject"))(component, engine, NULL);
    ((void (*)(void *, const void *, const void *))symbol(qml, "_ZN21QDeclarativeComponent7setDataERK10QByteArrayRK4QUrl"))(component, data, url);
    if (((int (*)(void *))symbol(qml, "_ZNK21QDeclarativeComponent7isErrorEv"))(component)) {
        ((void (*)(void *, const void *))symbol(qml, "_ZNK21QDeclarativeComponent11errorStringEv"))(error, component);
        const uint16_t *text = ((const uint16_t *(*)(void *))symbol(core, "_ZNK7QString5utf16Ev"))(error);
        for (; *text; text++) fputc(*text < 128 ? *text : '?', stderr);
        return 1;
    }
    void *object = ((void *(*)(void *, void *))symbol(qml, "_ZN21QDeclarativeComponent6createEP19QDeclarativeContext"))(component, NULL);
    if (object == NULL) return 1;
    puts("QT4_COMPONENT_CREATED");
    return 0;
}
