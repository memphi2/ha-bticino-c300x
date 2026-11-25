/* Offline Qt 4.8.7 ARM render probe, never installed on a device.
 * Opens the firmware's Qt with a framebuffer that is a plain file, shows one
 * QML file in a QDeclarativeView, runs the event loop for the given time and
 * saves the view as a PNG. Unlike qt4_runtime_probe.c it has a GUI, so Text
 * and the vendor components work. Usage: probe <file.qml> <out.png> <ms>
 */
#include <dlfcn.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>
#include <linux/fb.h>

#define W 800
#define H 480
static int depth = 16;

int ioctl(int fd, unsigned long request, ...)
{
    va_list ap; va_start(ap, request); void *arg = va_arg(ap, void *); va_end(ap);
    if (request == FBIOGET_VSCREENINFO) {
        struct fb_var_screeninfo *v = arg; memset(v, 0, sizeof *v);
        v->xres = v->xres_virtual = W; v->yres = v->yres_virtual = H; v->bits_per_pixel = depth;
        if (depth == 16) { v->red.offset = 11; v->red.length = 5; v->green.offset = 5; v->green.length = 6; v->blue.offset = 0; v->blue.length = 5; }
        else { v->red.offset = 16; v->red.length = 8; v->green.offset = 8; v->green.length = 8; v->blue.offset = 0; v->blue.length = 8;
               if (depth == 32) { v->transp.offset = 24; v->transp.length = 8; } }
        v->width = 152; v->height = 91;
        return 0;
    }
    if (request == FBIOGET_FSCREENINFO) {
        struct fb_fix_screeninfo *f = arg; memset(f, 0, sizeof *f);
        strcpy(f->id, "probe"); f->smem_len = W * H * (depth / 8); f->line_length = W * (depth / 8);
        f->type = FB_TYPE_PACKED_PIXELS; f->visual = FB_VISUAL_TRUECOLOR;
        return 0;
    }
    if (request == FBIOPUT_VSCREENINFO || request == FBIOBLANK || request == FBIOPAN_DISPLAY) return 0;
    return (int)syscall(SYS_ioctl, fd, request, arg);
}

static void *sym(void *lib, const char *name)
{
    void *v = dlsym(lib, name);
    if (!v) { fprintf(stderr, "%s: %s\n", name, dlerror()); exit(2); }
    return v;
}
static void *storage(void) { void *v = calloc(1, 65536); if (!v) exit(2); return v; }

int main(int argc, char **argv)
{
    extern char **environ;
    environ = argv + argc + 1;
    setbuf(stdout, NULL); setbuf(stderr, NULL);
    if (argc != 4) return 2;
    if (getenv("PROBE_DEPTH")) depth = (getenv("PROBE_DEPTH")[0] - 48) * 10 + getenv("PROBE_DEPTH")[1] - 48;
    static char *args[] = {"probe", "-qws", "-noswcursor", NULL}; static int one = 3;
    void *core = dlopen("libQtCoreE.so.4", RTLD_NOW | RTLD_GLOBAL);
    void *gui = dlopen("libQtGuiE.so.4", RTLD_NOW | RTLD_GLOBAL);
    void *qml = dlopen("libQtDeclarativeE.so.4", RTLD_NOW | RTLD_GLOBAL);
    if (!core || !gui || !qml) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    printf("QT4_RUNTIME_VERSION %s\n", ((const char *(*)(void))sym(core, "_Z8qVersionv"))());
    void *app = storage(), *view = storage(), *path = storage(), *url = storage(), *pix = storage();
    ((void (*)(void *, int *, char **, int, int))sym(gui, "_ZN12QApplicationC1ERiPPcNS_4TypeEi"))(app, &one, args, 2, 0x040807);
    ((void (*)(void *, void *))sym(qml, "_ZN16QDeclarativeViewC1EP7QWidget"))(view, NULL);
    ((void (*)(void *, const char *, int))sym(core, "_ZN7QString8fromUtf8EPKci"))(path, argv[1], -1);
    ((void (*)(void *, const void *))sym(core, "_ZN4QUrl13fromLocalFileERK7QString"))(url, path);
    ((void (*)(void *, const void *))sym(qml, "_ZN16QDeclarativeView9setSourceERK4QUrl"))(view, url);
    puts("STAGE source");
    int rect[4] = {0, 0, W - 1, H - 1};
    ((void (*)(void *, const int *))sym(gui, "_ZN7QWidget11setGeometryERK5QRect"))(view, rect);
    ((void (*)(void *, int))sym(gui, "_ZN7QWidget10setVisibleEb"))(view, 1);
    puts("STAGE shown");
    static int flags = 0; void (*process)(int *) = (void (*)(int *))sym(core, "_ZN16QCoreApplication13processEventsE6QFlagsIN10QEventLoop17ProcessEventsFlagEE");
    int rounds = 0; for (const char *p = argv[3]; *p >= 48 && *p <= 57; p++) rounds = rounds * 10 + (*p - 48); rounds /= 10;
    for (int i = 0; i < rounds; i++) { process(&flags); usleep(10000); }
    puts("STAGE loop done");
    ((void (*)(void *, void *, const int *))sym(gui, "_ZN7QPixmap10grabWidgetEP7QWidgetRK5QRect"))(pix, view, rect);
    puts("STAGE grabbed");
    void *out = storage();
    ((void (*)(void *, const char *, int))sym(core, "_ZN7QString8fromUtf8EPKci"))(out, argv[2], -1);
    int ok = ((int (*)(void *, const void *, const char *, int))sym(gui, "_ZNK7QPixmap4saveERK7QStringPKci"))(pix, out, "PNG", -1);
    printf("PROBE_SAVED %d %s\n", ok, argv[2]);
    fflush(NULL);
    _exit(ok ? 0 : 1);
}
