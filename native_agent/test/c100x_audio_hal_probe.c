/* Offline-only: original HAL executes, but every hardware/command boundary is intercepted. */
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void *app_logger;
int VERBOSITY_LEVEL;
static int state;

int board(void) __asm__("_Z9hal_boardv");
int board(void) { return 16; }
int hwversion(char *out) __asm__("_Z17hal_get_hwversionPc");
int hwversion(char *out) { strcpy(out, "04"); return 0; }
int audio_state(void) __asm__("_Z19hal_get_audio_statev");
int audio_state(void) { return state; }
int mixer(char *name, long value, int type) __asm__("_Z20change_mixer_controlPcli");
int mixer(char *name, long value, int type)
{
    printf("mixer:%s:%ld:%d\n", name, value, type);
    if (!strcmp(name, "Audio_State")) state = (int)value;
    return 0;
}
void debug(void *self, int level, const char *format, ...) __asm__("_ZN6logger5debugEiPKcz");
void debug(void *self, int level, const char *format, ...)
{ (void)self; (void)level; (void)format; }
void g_free(void *p) { free(p); }
char *g_strdup(const char *s) { return strdup(s); }
int call(char **args)
{
    fputs("command:", stdout);
    for (size_t i = 0; args[i]; ++i) printf("%s%s", i ? " " : "", args[i]);
    putchar('\n');
    return 0;
}

int main(int argc, char **argv)
{
    assert(argc == 5);
    void *handle = dlopen(argv[1], RTLD_LAZY | RTLD_LOCAL);
    if (!handle) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    state = atoi(argv[3]);
    if (!strcmp(argv[2], "state")) {
        int (*enable)(int);
        *(void **)&enable = dlsym(handle, "_Z16hal_audio_enable17audio_enable_type");
        assert(enable);
        printf("result:%d\n", enable(atoi(argv[4])));
    } else {
        int (*volume)(unsigned, int);
        *(void **)&volume = dlsym(handle, "_Z24hal_set_amplifier_volumej13volumes_types");
        assert(volume);
        printf("result:%d\n", volume((unsigned)atoi(argv[4]), 1));
    }
    dlclose(handle);
    return 0;
}
