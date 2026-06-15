#include "c300x_agent.h"

#if defined(C300X_GLIBC_COMPAT)

typedef int (*c300x_main_fn)(int, char **, char **);
typedef void (*c300x_lifecycle_fn)(void);

extern int c300x_old_libc_start_main(
    c300x_main_fn main_fn,
    int argc,
    char **argv,
    c300x_lifecycle_fn init_fn,
    c300x_lifecycle_fn fini_fn,
    c300x_lifecycle_fn rtld_fini_fn,
    void *stack_end
) __asm__("__libc_start_main");

__asm__(".symver c300x_old_libc_start_main,__libc_start_main@GLIBC_2.4");

int __wrap___libc_start_main(
    c300x_main_fn main_fn,
    int argc,
    char **argv,
    c300x_lifecycle_fn init_fn,
    c300x_lifecycle_fn fini_fn,
    c300x_lifecycle_fn rtld_fini_fn,
    void *stack_end
)
{
    return c300x_old_libc_start_main(
        main_fn,
        argc,
        argv,
        init_fn,
        fini_fn,
        rtld_fini_fn,
        stack_end
    );
}

#endif
