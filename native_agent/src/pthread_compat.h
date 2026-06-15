#ifndef C300X_PTHREAD_COMPAT_H
#define C300X_PTHREAD_COMPAT_H

#include <pthread.h>

#if defined(__arm__)
int c300x_pthread_create(
    pthread_t *thread,
    const pthread_attr_t *attr,
    void *(*start_routine)(void *),
    void *arg
);
int c300x_pthread_join(pthread_t thread, void **retval);
int c300x_pthread_detach(pthread_t thread);

#define pthread_create c300x_pthread_create
#define pthread_join c300x_pthread_join
#define pthread_detach c300x_pthread_detach
#endif

#endif
