#include "media_unit.h"

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "station_archive.h"

static pthread_mutex_t unit_mutex = PTHREAD_MUTEX_INITIALIZER;
static char requested[C300X_MEDIA_DEVADDR_LEN];
static char session[C300X_MEDIA_DEVADDR_LEN];

int c300x_media_devaddr_valid(const char *devaddr)
{
    char *end;
    long number;

    if (devaddr == NULL || !c300x_unit_where_valid(devaddr) || devaddr[0] != '2'
        || devaddr[1] < '0' || devaddr[1] > '9' || strlen(devaddr) >= C300X_MEDIA_DEVADDR_LEN) {
        return 0;
    }
    /* bt_answering_machine's rule: the unit's address after the leading 2
     * (the device type) is below 96. */
    number = strtol(devaddr + 1, &end, 10);
    return (*end == '\0' || *end == '#') && number < 96;
}

static const char *pick(const char *devaddr, const char *fallback)
{
    return c300x_media_devaddr_valid(devaddr) ? devaddr : c300x_media_devaddr_valid(fallback) ? fallback : "20";
}

void c300x_media_unit_request(const char *devaddr, const char *fallback, char *out, size_t out_len)
{
    pthread_mutex_lock(&unit_mutex);
    snprintf(requested, sizeof(requested), "%s", pick(devaddr, fallback));
    snprintf(out, out_len, "%s", requested);
    pthread_mutex_unlock(&unit_mutex);
}

void c300x_media_unit_begin(const char *fallback, char *out, size_t out_len)
{
    pthread_mutex_lock(&unit_mutex);
    snprintf(session, sizeof(session), "%s", pick(requested, fallback));
    snprintf(out, out_len, "%s", session);
    pthread_mutex_unlock(&unit_mutex);
}

void c300x_media_unit_end(void)
{
    pthread_mutex_lock(&unit_mutex);
    session[0] = '\0';
    pthread_mutex_unlock(&unit_mutex);
}

int c300x_media_unit_other(const char *devaddr)
{
    int other;

    pthread_mutex_lock(&unit_mutex);
    other = session[0] != '\0' && strcmp(session, devaddr) != 0;
    pthread_mutex_unlock(&unit_mutex);
    return other;
}
