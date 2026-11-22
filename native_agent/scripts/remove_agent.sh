#!/bin/sh
set -u

AGENT_DIR="${C300X_AGENT_DIR:-/home/bticino/cfg/extra/c300x-native-agent}"
BACKUP_ROOT="${C300X_BACKUP_ROOT:-/home/bticino/cfg/extra/c300x-device-file-backups}"
QML_PATCH="${C300X_QML_PATCH_SCRIPT:-$AGENT_DIR/qml_patch.sh}"
INIT_SCRIPT="${C300X_INIT_SCRIPT:-/etc/init.d/c300x-native-agent}"
INIT_LINK="${C300X_INIT_LINK:-/etc/rc5.d/S40c300x-native-agent}"
IPTABLES="${C300X_IPTABLES:-/etc/network/if-pre-up.d/iptables}"
IPTABLES6="${C300X_IPTABLES6:-/etc/network/if-pre-up.d/iptables6}"
SSH_INIT="${C300X_SSH_INIT:-/etc/init.d/dropbear}"
REBOOT="${C300X_REBOOT:-/sbin/reboot}"
IPTABLES_BACKUP="$BACKUP_ROOT/original/etc/network/if-pre-up.d/iptables"
IPTABLES6_BACKUP="$BACKUP_ROOT/original/etc/network/if-pre-up.d/iptables6"

if [ "${1:-}" != "remove" ] && [ "${1:-}" != "--run-from-tmp" ]; then
    printf 'Usage: %s remove\n' "$0" >&2
    exit 64
fi

REMOVE_WORK="$(mktemp -d "${TMPDIR:-/tmp}/c300x-remove-agent.XXXXXX")" || {
    printf 'Cannot create private removal workspace; keeping agent files and backups in place\n' >&2
    exit 1
}
RESTORE_STAGE=""
ROOT_WRITABLE=0
cleanup_workspace() {
    cleanup_status=$?
    cleanup_failed=0
    trap - EXIT HUP INT TERM
    if [ -n "$RESTORE_STAGE" ]; then
        rm -rf "$RESTORE_STAGE" || cleanup_failed=1
    fi
    if [ "$ROOT_WRITABLE" = 1 ]; then
        mount -o remount,ro / >/dev/null 2>&1 || cleanup_failed=1
    fi
    rm -rf "$REMOVE_WORK" || cleanup_failed=1
    if [ "$cleanup_status" = 0 ]; then
        cleanup_status=$cleanup_failed
    fi
    exit "$cleanup_status"
}
trap cleanup_workspace EXIT
trap 'exit 130' HUP INT TERM
TMP_SELF="$REMOVE_WORK/remove_agent.sh"

if [ "${1:-}" = "remove" ]; then
    if ! cp "$0" "$TMP_SELF" || ! chmod 700 "$TMP_SELF"; then
        printf 'Cannot stage removal script; keeping agent files and backups in place\n' >&2
        exit 1
    fi
    # Keep the parent cleanup trap while the copied script survives agent removal.
    (exec "$TMP_SELF" --run-from-tmp)
    exit $?
fi

start_ssh() {
    "$SSH_INIT" start >/dev/null 2>&1 || true
}

remount_root_rw() {
    mount -o remount,rw / >/dev/null 2>&1 || return 1
    ROOT_WRITABLE=1
}

remount_root_ro() {
    mount -o remount,ro / >/dev/null 2>&1 || return 1
    ROOT_WRITABLE=0
}

restore_qml() {
    if [ ! -x "$QML_PATCH" ]; then
        printf 'Cannot verify GUI restoration without executable patch script; keeping agent files and backups in place\n' >&2
        exit 1
    fi
    if [ -x "$QML_PATCH" ]; then
        status="$(C300X_QML_SOURCE_DIR="$AGENT_DIR/qml" "$QML_PATCH" status 2>/dev/null || true)"
        if printf '%s' "$status" | grep -F -q '"state":"original"' \
            && printf '%s' "$status" | grep -F -q '"core_state":"original"' \
            && printf '%s' "$status" | grep -F -q '"media_user_label_state":"original"'; then
            return 0
        fi
        # A display library without a valid backup cannot be restored; it does
        # not keep the display files from being removed (see below).
        if ! status="$(C300X_QML_SOURCE_DIR="$AGENT_DIR/qml" "$QML_PATCH" restore-all 2>/dev/null)" \
            || ! printf '%s' "$status" | grep -F -q -e '"ok":true' -e 'display_library_restore_failed' \
            || ! printf '%s' "$status" | grep -F -q '"state":"original"' \
            || ! printf '%s' "$status" | grep -F -q '"core_state":"original"' \
            || ! printf '%s' "$status" | grep -F -q '"media_user_label_state":"original"'; then
            printf 'Failed to restore Display patch; keeping agent files and backups in place\n' >&2
            exit 1
        fi
    fi
}

replace_firewall_file() {
    restore_source="$1"
    restore_target="$2"
    if [ -L "$restore_target" ] || { [ -e "$restore_target" ] && [ ! -f "$restore_target" ]; }; then
        return 1
    fi
    # A private sibling directory keeps staging on the destination filesystem.
    RESTORE_STAGE="$(mktemp -d "${restore_target}.c300x-restore.XXXXXX")" || return 1
    restore_rc=0
    if [ -f "$restore_target" ]; then
        cp -p "$restore_target" "$RESTORE_STAGE/file" || restore_rc=1
    else
        : > "$RESTORE_STAGE/file" && chmod 755 "$RESTORE_STAGE/file" || restore_rc=1
    fi
    if [ "$restore_rc" = 0 ]; then
        cat "$restore_source" > "$RESTORE_STAGE/file" &&
            cmp -s "$restore_source" "$RESTORE_STAGE/file" &&
            mv -f "$RESTORE_STAGE/file" "$restore_target" || restore_rc=1
    fi
    if rm -rf "$RESTORE_STAGE"; then
        RESTORE_STAGE=""
    else
        restore_rc=1
    fi
    return "$restore_rc"
}

remove_managed_block() {
    target="$1"
    begin="$2"
    end="$3"
    tmp="$REMOVE_WORK/managed-block"

    [ -f "$target" ] || return 0
    if ! awk -v begin="$begin" -v end="$end" '
        $0 == begin {skip = 1; next}
        $0 == end {skip = 0; next}
        skip != 1 {print}
    ' "$target" > "$tmp"; then
        rm -f "$tmp"
        return 1
    fi
    if ! replace_firewall_file "$tmp" "$target"; then
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

    remount_root_rw || return 1
    if [ -f "$backup" ]; then
        if ! replace_firewall_file "$backup" "$target"; then
            remount_root_ro
            return 1
        fi
    else
        if ! remove_managed_block "$target" "$begin" "$end"; then
            remount_root_ro
            return 1
        fi
    fi
    remount_root_ro
}

remove_startup() {
    remount_root_rw || return 1
    startup_rc=0
    rm -f "$INIT_LINK" "$INIT_SCRIPT" || startup_rc=$?
    remount_root_ro || {
        if [ "$startup_rc" = 0 ]; then startup_rc=1; fi
    }
    return "$startup_rc"
}

stop_agent() {
    if [ -f "$AGENT_DIR/c300x-agent-native.pid" ]; then
        start-stop-daemon -K -p "$AGENT_DIR/c300x-agent-native.pid" >/dev/null 2>&1 || true
    fi
    pidof c300x-agent-native >/dev/null 2>&1 && killall c300x-agent-native >/dev/null 2>&1 || true
}

restore_media_patches() {
    if ! C300X_AUDIO_BACKUP_DIR="$BACKUP_ROOT/original" \
        C300X_ROUTING_BACKUP_DIR="$BACKUP_ROOT/original/home/bticino/bin" \
        "$AGENT_DIR/c300x-agent-native" --restore-media-patches; then
        printf 'Failed to restore media patches; keeping agent files and backups in place\n' >&2
        exit 1
    fi
}

# The Display restore puts the stock display library back; this covers a
# display that was restored before, with the library still changed. It runs
# last, before the reboot: the running display keeps the replaced file open,
# so the root file system stays writable until then. Without a valid backup
# the changed library stays, which only keeps the wider tap tolerance.
# Without a valid stock backup the library stays as it is (wider tap
# tolerance); any other failure keeps the backup for another removal.
restore_display_library() {
    touch_result="$("$AGENT_DIR/c300x-agent-native" --display-touch restore 2>/dev/null || true)"
    case "$touch_result" in
        *'"ok":true'*) return 0 ;;
        *'"error":"touch_backup_invalid"'*)
            printf 'Display library not restored; it keeps the wider tap tolerance\n' >&2
            return 0 ;;
    esac
    return 1
}

schedule_reboot() {
    "$REBOOT" >/dev/null 2>&1 &
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
if ! restore_display_library; then
    printf 'Failed to restore the display library; keeping agent files and backups in place\n' >&2
    exit 1
fi
stop_agent
restore_media_patches
if ! remove_startup; then
    printf 'Failed to remove startup files; keeping agent files and backups in place\n' >&2
    exit 1
fi
rm -rf "$AGENT_DIR" "$BACKUP_ROOT"
start_ssh
schedule_reboot

exit 0
