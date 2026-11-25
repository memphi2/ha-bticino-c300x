/* Execute pure JS with original ARM QtQml, never a GUI or vendor plugin.
 * As in qt5_compile_probe.c, exported C++ ABI uses oversized aligned storage.
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void *symbol(void *library, const char *name)
{
    void *result = dlsym(library, name);
    if (result == NULL) { fprintf(stderr, "%s: %s\n", name, dlerror()); exit(2); }
    return result;
}

static void *storage(void)
{
    void *result = calloc(1, 65536);
    if (result == NULL) exit(2);
    return result;
}

int main(int argc, char **argv)
{
    extern char **environ;
    environ = argv + argc + 1;
    if (argc != 2) return 2;
    void *core = dlopen("libQt5Core.so.5", RTLD_NOW | RTLD_GLOBAL);
    void *qml = dlopen("libQt5Qml.so.5", RTLD_NOW | RTLD_GLOBAL);
    if (core == NULL || qml == NULL) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    printf("FIRMWARE_QT_VERSION=%s\n", ((const char *(*)(void))symbol(core, "qVersion"))());
    FILE *file = fopen(argv[1], "rb");
    if (file == NULL || fseek(file, 0, SEEK_END) != 0) return 2;
    long length = ftell(file);
    if (length < 0 || length > 1048576 || fseek(file, 0, SEEK_SET) != 0) return 2;
    char *source = calloc(1, (size_t)length + 1);
    if (source == NULL || fread(source, 1, (size_t)length, file) != (size_t)length) return 2;
    fclose(file);
    void *app = storage(), *engine = storage(), *script = storage(), *name = storage();
    void *result = storage(), *message = storage();
    ((void (*)(void *, int *, char **, int))symbol(core, "_ZN16QCoreApplicationC1ERiPPci"))(app, &argc, argv, 0);
    ((void (*)(void *, void *))symbol(qml, "_ZN9QJSEngineC1EP7QObject"))(engine, NULL);
    ((void (*)(void *, const char *, int))symbol(core, "_ZN7QString15fromUtf8_helperEPKci"))(script, source, (int)length);
    ((void (*)(void *, const char *, int))symbol(core, "_ZN7QString15fromUtf8_helperEPKci"))(name, argv[1], (int)strlen(argv[1]));
    ((void (*)(void *, void *, void *, void *, int))symbol(qml, "_ZN9QJSEngine8evaluateERK7QStringS2_i"))(result, engine, script, name, 1);
    int failed = ((int (*)(void *))symbol(qml, "_ZNK8QJSValue7isErrorEv"))(result);
    ((void (*)(void *, void *))symbol(qml, "_ZNK8QJSValue8toStringEv"))(message, result);
    const uint16_t *text = ((const uint16_t *(*)(void *))symbol(core, "_ZNK7QString5utf16Ev"))(message);
    printf("JS_RESULT=");
    for (; *text; text++) putchar(*text < 128 ? *text : '?');
    printf("\nJS_ERROR=%d\n", failed);
    return failed ? 1 : 0;
}
