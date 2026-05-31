#include "pthread_compat.h"

#if defined(__arm__)

extern int c300x_old_pthread_create(
    pthread_t *thread,
    const pthread_attr_t *attr,
    void *(*start_routine)(void *),
    void *arg
);
extern int c300x_old_pthread_join(pthread_t thread, void **retval);
extern int c300x_old_pthread_detach(pthread_t thread);

__asm__(".symver c300x_old_pthread_create,pthread_create@GLIBC_2.4");
__asm__(".symver c300x_old_pthread_join,pthread_join@GLIBC_2.4");
__asm__(".symver c300x_old_pthread_detach,pthread_detach@GLIBC_2.4");

int c300x_pthread_create(
    pthread_t *thread,
    const pthread_attr_t *attr,
    void *(*start_routine)(void *),
    void *arg
)
{
    return c300x_old_pthread_create(thread, attr, start_routine, arg);
}

int c300x_pthread_join(pthread_t thread, void **retval)
{
    return c300x_old_pthread_join(thread, retval);
}

int c300x_pthread_detach(pthread_t thread)
{
    return c300x_old_pthread_detach(thread);
}

#endif
