#ifndef C300X_FOREIGN_SERVICES_H
#define C300X_FOREIGN_SERVICES_H

/* Services that third-party rooting and MQTT tools add to a station. None of
 * them is on a stock image of 1.7.19, 2.0.2, 3.0.6 or the C100X 1.5.8. */
#ifndef C300X_FOREIGN_ROOT
#define C300X_FOREIGN_ROOT ""
#endif
#ifndef C300X_PROC_NET_DIR
#define C300X_PROC_NET_DIR "/proc/net"
#endif

/* Name of the first service that keeps SSH running on its own (its own
 * dropbear or a watchdog that restarts the factory one), or NULL. */
const char *c300x_ssh_foreign_manager(void);
/* 1 when a TCP or TCP6 socket listens on port 22. */
int c300x_ssh_port_listening(void);

#endif
