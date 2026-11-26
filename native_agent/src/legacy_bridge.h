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
#define C300X_LEGACY_MQTT_INIT_LINK C300X_FOREIGN_ROOT "/etc/rc5.d/S99TcpDump2Mqtt"
#define C300X_LEGACY_MQTT_INIT_TARGET "../tcpdump2mqtt/TcpDump2Mqtt.sh"

/* Both answer 1 on success, also when there is no regular bridge file, and
 * set *changed when they changed its mode. Call them with / writable. Unblock
 * gives a bridge without execute bits the recorded mode, or without a record
 * (the agent was removed meanwhile) its read bits as execute bits. */
int c300x_legacy_bridge_block(int *changed);
int c300x_legacy_bridge_unblock(int *changed);
/* Legacy MQTT start off and on, with / writable: off blocks the bridge before
 * the start link goes, on gives its mode back before the link comes. A link
 * step that fails undoes the bridge step, so no half state stays. */
int c300x_legacy_mqtt_start_off(int *changed);
int c300x_legacy_mqtt_start_on(int *changed);
/* The bridge file is there and not executable since our block. */
int c300x_legacy_bridge_blocked(void);
/* A watchdog that restarts the bridge is installed. */
int c300x_legacy_bridge_watchdog(void);

#endif
