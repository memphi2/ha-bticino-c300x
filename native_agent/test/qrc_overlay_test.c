/* Stands in for the Qt display program: provides the function qrc_overlay.so
   registers its resource with and prints what it received. */
#include <stdio.h>
#include <stdlib.h>

static int calls;
static int version;
static char tree_mark = '-';
static char names_mark = '-';
static char data_mark = '-';

unsigned char register_resource(int, const unsigned char *, const unsigned char *, const unsigned char *)
    __asm__("_Z21qRegisterResourceDataiPKhS0_S0_");

unsigned char register_resource(
    int given_version,
    const unsigned char *tree,
    const unsigned char *names,
    const unsigned char *data
)
{
    const char *accept = getenv("QRC_TEST_ACCEPT");

    calls++;
    version = given_version;
    tree_mark = (char)tree[5];
    names_mark = (char)names[1];
    data_mark = (char)data[3];
    return accept == NULL || accept[0] != '0';
}

int main(void)
{
    const char *preload = getenv("LD_PRELOAD");

    printf(
        "{\"calls\":%d,\"version\":%d,\"marks\":[%d,%d,%d],\"preload_kept\":%s}\n",
        calls, version, tree_mark, names_mark, data_mark,
        preload != NULL && preload[0] != '\0' ? "true" : "false"
    );
    return 0;
}
