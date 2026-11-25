/* Compile only with private firmware Qt 5 libraries. Never construct the
 * vendor application, vendor plugins, QML objects or a display connection.
 * Exported ABI calls use oversized aligned storage; no Qt headers available.
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
    if (argc < 5) return 2;
    void *core = dlopen("libQt5Core.so.5", RTLD_NOW | RTLD_GLOBAL);
    if (core == NULL) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    printf("FIRMWARE_QT_VERSION=%s\n", ((const char *(*)(void))symbol(core, "qVersion"))());
    void *qml = dlopen("libQt5Qml.so.5", RTLD_NOW | RTLD_GLOBAL);
    if (qml == NULL) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    void *app = storage(), *engine = storage(), *path = storage();
    ((void (*)(void *, int *, char **, int))symbol(core, "_ZN16QCoreApplicationC1ERiPPci"))(app, &argc, argv, 0);
    ((void (*)(void *, void *))symbol(qml, "_ZN10QQmlEngineC1EP7QObject"))(engine, NULL);
    for (int i = 1; i <= 3; i++) {
        ((void (*)(void *, const char *, int))symbol(core, "_ZN7QString15fromUtf8_helperEPKci"))(path, argv[i], (int)strlen(argv[i]));
        ((void (*)(void *, void *))symbol(qml, "_ZN10QQmlEngine13addImportPathERK7QString"))(engine, path);
    }
    int failures = 0;
    for (int i = 4; i < argc; i++) {
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
    }
    printf("COMPILE_FAILURES=%d\n", failures);
    return failures ? 1 : 0;
}
