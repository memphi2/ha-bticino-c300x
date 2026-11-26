#ifndef C300X_SSH_STATUS_H
#define C300X_SSH_STATUS_H

#ifndef C300X_SSH_INIT_SCRIPT
#define C300X_SSH_INIT_SCRIPT "/etc/init.d/dropbear"
#endif
#ifndef C300X_SSH_STATUS_COMMAND
/* The factory dropbear, as the stock init script starts it on all four
 * firmwares. The stock script stops the listener by pidfile. Established SSH
 * sessions can keep their own dropbear processes after a successful stop. */
#define C300X_SSH_STATUS_COMMAND \
    "file=/var/run/dropbear.pid; [ -e \"$file\" ] || exit 1; " \
    "read -r pid < \"$file\" || exit 2; case $pid in ''|*[!0-9]*) exit 2;; esac; " \
    "[ /proc/\"$pid\"/exe -ef /usr/sbin/dropbear ]"
#endif
/* A hanging init script or status check must not hold the maintenance
 * slot, and with it every other maintenance request, for good. */
#ifndef C300X_SSH_COMMAND_TIMEOUT_MS
#define C300X_SSH_COMMAND_TIMEOUT_MS 60000
#endif
#ifndef C300X_SSH_STATUS_TIMEOUT_MS
#define C300X_SSH_STATUS_TIMEOUT_MS 15000
#endif

/* factory: 1 the factory dropbear runs, 0 it does not, -1 unknown. Sends the
 * SSH status and returns 1, or sends nothing and returns 0 when require is 0
 * or 1 and SSH does not end up in that state. */
int c300x_ssh_send_status(int fd, int factory, int require);
/* Answers 409 and returns 1 when a foreign service keeps SSH listening:
 * the agent then neither starts nor stops anything. */
int c300x_ssh_refuse_managed(int fd);

#endif
