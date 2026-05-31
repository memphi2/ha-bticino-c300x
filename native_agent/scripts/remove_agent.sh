#!/bin/sh
set -u

AGENT_DIR="${C300X_AGENT_DIR:-/home/bticino/cfg/extra/c300x-native-agent}"
BACKUP_ROOT="${C300X_BACKUP_ROOT:-/home/bticino/cfg/extra/c300x-device-file-backups}"
QML_PATCH="${C300X_QML_PATCH_SCRIPT:-$AGENT_DIR/qml_patch.sh}"
INIT_SCRIPT="${C300X_INIT_SCRIPT:-/etc/init.d/c300x-native-agent}"
INIT_LINK="${C300X_INIT_LINK:-/etc/rc5.d/S40c300x-native-agent}"
IPTABLES="${C300X_IPTABLES:-/etc/network/if-pre-up.d/iptables}"
IPTABLES6="${C300X_IPTABLES6:-/etc/network/if-pre-up.d/iptables6}"
IPTABLES_BACKUP="$BACKUP_ROOT/original/etc/network/if-pre-up.d/iptables"
IPTABLES6_BACKUP="$BACKUP_ROOT/original/etc/network/if-pre-up.d/iptables6"
TMP_SELF="/tmp/c300x-remove-agent.$$"

if [ "${1:-}" != "remove" ] && [ "${1:-}" != "--run-from-tmp" ]; then
    printf 'Usage: %s remove\n' "$0" >&2
    exit 64
fi

if [ "${1:-}" = "remove" ]; then
    cp "$0" "$TMP_SELF"
    chmod 700 "$TMP_SELF"
    exec "$TMP_SELF" --run-from-tmp
fi

start_ssh() {
    /etc/init.d/dropbear start >/dev/null 2>&1 || true
}

remount_root_rw() {
    mount -o remount,rw / >/dev/null 2>&1 || true
}

remount_root_ro() {
    mount -o remount,ro / >/dev/null 2>&1 || true
}

restore_qml() {
    if [ -x "$QML_PATCH" ]; then
        status="$(C300X_QML_SOURCE_DIR="$AGENT_DIR/qml" "$QML_PATCH" status 2>/dev/null || true)"
        if printf '%s' "$status" | grep -F -q '"state":"original"'; then
            return 0
        fi
        if ! C300X_QML_SOURCE_DIR="$AGENT_DIR/qml" "$QML_PATCH" restore >/dev/null 2>&1; then
            printf 'Failed to restore QML patch; keeping agent files and backups in place\n' >&2
            exit 1
        fi
    fi
}

remove_managed_block() {
    target="$1"
    begin="$2"
    end="$3"
    tmp="/tmp/c300x-managed-block.$$"

    [ -f "$target" ] || return 0
    if ! awk -v begin="$begin" -v end="$end" '
        $0 == begin {skip = 1; next}
        $0 == end {skip = 0; next}
        skip != 1 {print}
    ' "$target" > "$tmp"; then
        rm -f "$tmp"
        return 1
    fi
    if ! cat "$tmp" > "$target"; then
        rm -f "$tmp"
        return 1
    fi
    rm -f "$tmp"
}

restore_file_or_remove_block() {
    target="$1"
    backup="$2"
    begin="$3"
    end="$4"

    remount_root_rw
    if [ -f "$backup" ]; then
        if ! cp "$backup" "$target"; then
            remount_root_ro
            return 1
        fi
        chmod 755 "$target" >/dev/null 2>&1 || true
    else
        if ! remove_managed_block "$target" "$begin" "$end"; then
            remount_root_ro
            return 1
        fi
    fi
    remount_root_ro
}

remove_startup() {
    remount_root_rw
    rm -f "$INIT_LINK" "$INIT_SCRIPT"
    remount_root_ro
}

stop_agent() {
    if [ -f "$AGENT_DIR/c300x-agent-native.pid" ]; then
        start-stop-daemon -K -p "$AGENT_DIR/c300x-agent-native.pid" >/dev/null 2>&1 || true
    fi
    pidof c300x-agent-native >/dev/null 2>&1 && killall c300x-agent-native >/dev/null 2>&1 || true
}

schedule_reboot() {
    /sbin/reboot >/dev/null 2>&1 &
}

start_ssh
restore_qml
if ! restore_file_or_remove_block "$IPTABLES6" "$IPTABLES6_BACKUP" "# c300x-native-agent ipv6 firewall begin" "# c300x-native-agent ipv6 firewall end"; then
    printf 'Failed to restore IPv6 firewall patch; keeping agent files and backups in place\n' >&2
    exit 1
fi
if ! restore_file_or_remove_block "$IPTABLES" "$IPTABLES_BACKUP" "# c300x-native-agent firewall begin" "# c300x-native-agent firewall end"; then
    printf 'Failed to restore IPv4 firewall patch; keeping agent files and backups in place\n' >&2
    exit 1
fi
remove_startup
stop_agent
rm -rf "$AGENT_DIR" "$BACKUP_ROOT"
start_ssh
rm -f "$TMP_SELF"
schedule_reboot

exit 0
