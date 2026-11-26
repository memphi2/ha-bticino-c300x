#ifndef C300X_LEGACY_BRIDGE_H
#define C300X_LEGACY_BRIDGE_H

#include "foreign_services.h"

/* The TcpDump2Mqtt bridge of the legacy MQTT setup. fquinto's watchdog
 * (/etc/init.d/bt_service_watchdog) runs it again every 60 s, so while legacy
 * MQTT is off the bridge loses its execute bits: nothing can start it, also
 * after a reboot. The watchdog itself is left alone. The previous mode is
 * kept on the persistent cfg partition and given back on enable. */
#define C300X_LEGACY_MQTT_BRIDGE C300X_FOREIGN_ROOT "/etc/tcpdump2mqtt/TcpDump2Mqtt"
#define C300X_LEGACY_MQTT_BRIDGE_MODE_DIR \
    C300X_FOREIGN_ROOT "/home/bticino/cfg/extra/c300x-device-file-backups/legacy-mqtt"
#define C300X_LEGACY_MQTT_BRIDGE_MODE C300X_LEGACY_MQTT_BRIDGE_MODE_DIR "/bridge-mode"

/* Both answer 1 on success, also when there is no regular bridge file, and
 * set *changed when they changed its mode. Call them with / writable. */
int c300x_legacy_bridge_block(int *changed);
int c300x_legacy_bridge_unblock(int *changed);
/* The bridge file is there and not executable since our block. */
int c300x_legacy_bridge_blocked(void);
/* A watchdog that restarts the bridge is installed. */
int c300x_legacy_bridge_watchdog(void);

#endif
