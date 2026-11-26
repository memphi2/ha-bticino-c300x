#ifdef __arm__
#ifndef _LARGEFILE64_SOURCE
#define _LARGEFILE64_SOURCE 1
#endif
#endif
#include "legacy_bridge.h"

#include "device_file.h"
#include "proc_probe.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#ifdef __arm__
#include <sys/syscall.h>
/* The station's glibc 2.26 has no plain fstat symbol. */
#define BRIDGE_STAT struct stat64
#define bridge_fstat(fd, st) ((int)syscall(SYS_fstat64, (fd), (st)))
#else
#define BRIDGE_STAT struct stat
#define bridge_fstat(fd, st) fstat((fd), (st))
#endif

/* The regular bridge file, never through a link. -1 with *absent set when
 * there is none to change. */
static int open_bridge(mode_t *mode, int *absent)
{
    BRIDGE_STAT st;
    int fd = open(C300X_LEGACY_MQTT_BRIDGE, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);

    *absent = fd < 0 && (errno == ENOENT || errno == ELOOP);
    if (fd >= 0 && (bridge_fstat(fd, &st) != 0 || !S_ISREG(st.st_mode))) {
        *absent = 1;
        close(fd);
        return -1;
    }
    if (fd >= 0) {
        *mode = st.st_mode & 07777;
    }
    return fd;
}

static int set_mode(int fd, mode_t mode, int *changed)
{
    if (fchmod(fd, mode) != 0) {
        return 0;
    }
    if (changed != NULL) {
        *changed = 1;
    }
    return 1;
}

int c300x_legacy_bridge_block(int *changed)
{
    char text[16];
    mode_t mode = 0;
    int absent, ok = 1;
    int fd = open_bridge(&mode, &absent);

    if (fd < 0) {
        return absent;
    }
    if ((mode & 0111) != 0) {
        /* The record first: a failed chmod then only restores the same mode. */
        snprintf(text, sizeof(text), "%04o\n", (unsigned)(mode & 07777));
        ok = c300x_device_file_mkdir_p(C300X_LEGACY_MQTT_BRIDGE_MODE_DIR)
            && c300x_device_file_write(C300X_LEGACY_MQTT_BRIDGE_MODE, text, strlen(text))
            && set_mode(fd, mode & ~(mode_t)0111, changed);
    }
    close(fd);
    return ok;
}

/* The recorded mode when it belongs to the blocked file, else its read bits
 * made executable. */
static mode_t recorded_mode(mode_t blocked)
{
    char text[16] = "";
    char *end = NULL;
    unsigned long value;
    FILE *file = fopen(C300X_LEGACY_MQTT_BRIDGE_MODE, "re");

    if (file != NULL) {
        if (fgets(text, sizeof(text), file) == NULL) {
            text[0] = '\0';
        }
        fclose(file);
    }
    value = strtoul(text, &end, 8);
    if (end != text && (*end == '\n' || *end == '\0') && value <= 07777 && (value & 0111) != 0
        && ((mode_t)value & ~(mode_t)0111) == blocked) {
        return (mode_t)value;
    }
    return blocked | ((blocked & 0444) >> 2);
}

int c300x_legacy_bridge_unblock(int *changed)
{
    mode_t mode = 0;
    int absent, ok, fd;

    if (access(C300X_LEGACY_MQTT_BRIDGE_MODE, F_OK) != 0) {
        return errno == ENOENT;
    }
    fd = open_bridge(&mode, &absent);
    ok = fd >= 0 ? (mode & 0111) != 0 || set_mode(fd, recorded_mode(mode), changed) : absent;
    if (fd >= 0) {
        close(fd);
    }
    return ok && (unlink(C300X_LEGACY_MQTT_BRIDGE_MODE) == 0 || errno == ENOENT);
}

int c300x_legacy_bridge_blocked(void)
{
    mode_t mode = 0;
    int absent;
    int fd = open_bridge(&mode, &absent);
    int blocked = fd >= 0 && (mode & 0111) == 0 && access(C300X_LEGACY_MQTT_BRIDGE_MODE, F_OK) == 0;

    if (fd >= 0) {
        close(fd);
    }
    return blocked;
}

int c300x_legacy_bridge_watchdog(void)
{
    return c300x_file_contains_literal(C300X_FOREIGN_ROOT "/etc/init.d/bt_service_watchdog",
        "/etc/tcpdump2mqtt/TcpDump2Mqtt");
}
