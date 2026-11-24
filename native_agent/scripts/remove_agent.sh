#!/bin/sh
set -u

AGENT_DIR="${C300X_AGENT_DIR:-/home/bticino/cfg/extra/c300x-native-agent}"
BACKUP_ROOT="${C300X_BACKUP_ROOT:-/home/bticino/cfg/extra/c300x-device-file-backups}"
QML_PATCH="${C300X_QML_PATCH_SCRIPT:-$AGENT_DIR/qml_patch.sh}"
C100X_MARKER="${C300X_QML_C100X_MARKER:-/home/bticino/bin/gui/BtClass100}"
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
STARTUP_ACTIVE=0
STARTUP_RO_FAILED=0
MEDIA_REBOOT_REQUIRED=0
FINAL_DELETE_STARTED=0
AGENT_STOPPED=0
cleanup_workspace() {
    cleanup_status=$?
    cleanup_failed=0
    keep_workspace=0
    trap - EXIT HUP INT TERM
    if [ "$STARTUP_ACTIVE" = 1 ]; then
        if [ "$FINAL_DELETE_STARTED" = 1 ]; then
            keep_workspace=1
            printf 'Final deletion did not complete; remaining files and startup recovery retained at %s. No reboot scheduled\n' "$REMOVE_WORK" >&2
        fi
        if [ "$FINAL_DELETE_STARTED" = 1 ] && ! agent_tree_unchanged; then
            cleanup_failed=1
            printf 'Agent tree changed or cannot be verified; startup remains disabled. Repair the agent installation before restoring startup from %s/startup; preserve remaining backups and do not reboot until recovery is complete\n' "$REMOVE_WORK" >&2
        elif restore_startup; then
            printf 'Original startup entries restored; removal aborted, no reboot scheduled\n' >&2
            if [ "$STARTUP_RO_FAILED" = 1 ]; then
                if [ "$MEDIA_REBOOT_REQUIRED" = 1 ]; then
                    printf 'The media restore verified stock files on disk while the patched media process is still running\n' >&2
                fi
                printf 'Root read-only remount failed after media restoration; perform a full device reboot before retrying removal\n' >&2
            fi
        else
            cleanup_failed=1
            keep_workspace=1
            printf 'Startup rollback failed; recovery files retained at %s/startup. Do not reboot until the original startup entries are restored\n' "$REMOVE_WORK" >&2
        fi
    fi
    if [ -n "$RESTORE_STAGE" ]; then
        rm -rf "$RESTORE_STAGE" || cleanup_failed=1
    fi
    if [ "$ROOT_WRITABLE" = 1 ]; then
        mount -o remount,ro / >/dev/null 2>&1 || cleanup_failed=1
    fi
    if [ "$keep_workspace" = 0 ]; then
        rm -rf "$REMOVE_WORK" || cleanup_failed=1
    fi
    if [ "$cleanup_status" = 0 ]; then
        cleanup_status=$cleanup_failed
    fi
    if [ "$cleanup_status" != 0 ] && [ "$AGENT_STOPPED" = 1 ] && [ "$keep_workspace" = 0 ] \
        && [ -x "$INIT_SCRIPT" ] && [ -x "$AGENT_DIR/c300x-agent-native" ]; then
        if "$INIT_SCRIPT" restart >/dev/null 2>&1 && "$INIT_SCRIPT" status >/dev/null 2>&1; then
            printf 'Agent started again so the removal can be retried\n' >&2
        else
            printf 'Agent could not be started again; start it with %s restart\n' "$INIT_SCRIPT" >&2
        fi
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

regular_unlinked_path() {
    [ -f "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %h "$1")" = 1 ] || return 1
    check_path=$1
    case "$check_path" in /*) ;; *) return 1 ;; esac
    case "$check_path" in *'/../'*|*'/./'*|*/..|*/.|*'//'*) return 1 ;; esac
    while [ "$check_path" != / ]; do
        [ ! -L "$check_path" ] || return 1
        check_path=${check_path%/*}
        [ -n "$check_path" ] || check_path=/
    done
}

c100x_stock_file() {
    regular_unlinked_path "$1" && [ "$(sha256sum "$1" | awk '{print $1}')" = "$2" ]
}

c100x_stock_display() {
    c100x_stock_file "$c100x_gui/main.qml" ff1740e9742951f5cda2225d605eae06141f43ee26d900ca21d7fdf14960e6fb \
        && c100x_stock_file "$c100x_gui/MainPage.qml" ba3edae9b9e670dad86894f93747f510f07c2389f498697e5d20dd95b4cb8e80 \
        && c100x_stock_file "$c100x_gui/EventManager.qml" 3ca4b5e8c27c8c8b283d533106091072e25632bb090d414ee4c1d93f3a06b181
}

restore_c100x_qml() {
    c100x_gui=${C100X_GUI_DIR:-/home/bticino/bin/gui/skins/default}
    c100x_payload=$AGENT_DIR/qml/c100x_bundle.sh
    # Old packages had no adapter payload. Exact stock needs no recovery code.
    c100x_stock_display && return 0
    if ! regular_unlinked_path "$c100x_payload" || [ ! -x "$c100x_payload" ] \
        || ! C100X_GUI_DIR="$c100x_gui" C100X_GUI_BIN="$C100X_MARKER" \
            C100X_BACKUP_DIR="$BACKUP_ROOT/c100x-display" "$c100x_payload" restore \
            >/dev/null 2>&1 || ! c100x_stock_display; then
        printf 'Failed to restore C100X display; keeping agent files and backups in place\n' >&2
        exit 1
    fi
}

restore_qml() {
    if [ -e "$C100X_MARKER" ]; then restore_c100x_qml; return; fi
    if [ ! -x "$QML_PATCH" ]; then
        printf 'Cannot verify GUI restoration without executable patch script; keeping agent files and backups in place\n' >&2
        exit 1
    fi
    if [ -x "$QML_PATCH" ]; then
        status="$(C300X_QML_SOURCE_DIR="$AGENT_DIR/qml" "$QML_PATCH" status 2>/dev/null || true)"
        if ! printf '%s' "$status" | grep -F -q '"transaction":' \
            && printf '%s' "$status" | grep -F -q '"state":"original"' \
            && printf '%s' "$status" | grep -F -q '"core_state":"original"' \
            && printf '%s' "$status" | grep -F -q '"media_user_label_state":"original"'; then
            return 0
        fi
        # A display library without a valid backup cannot be restored; it does
        # not keep the display files from being removed (see below).
        if ! status="$(C300X_QML_SOURCE_DIR="$AGENT_DIR/qml" "$QML_PATCH" restore-all 2>/dev/null)" \
            || ! printf '%s' "$status" | grep -F -q -e '"ok":true' -e 'display_library_restore_failed' \
            || printf '%s' "$status" | grep -F -q '"transaction":"stuck"' \
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

strip_managed_blocks() {
    awk '
        $0 == "# c300x-native-agent firewall begin" || $0 == "# c300x-native-agent ipv6 firewall begin" {
            if (skip) exit 3
            skip = 1
            next
        }
        $0 == "# c300x-native-agent firewall end" || $0 == "# c300x-native-agent ipv6 firewall end" {
            if (!skip) exit 3
            skip = 0
            next
        }
        skip != 1 {print}
        END {if (skip) exit 3}
    ' "$1" > "$2"
}

restore_firewall() {
    target="$1"
    backup="$2"
    tmp="$REMOVE_WORK/managed-block"

    remount_root_rw || return 1
    if [ -e "$target" ] || [ -L "$target" ]; then
        if ! strip_managed_blocks "$target" "$tmp"; then
            printf 'Cannot remove the agent firewall block from %s\n' "$target" >&2
            firewall_rc=1
        elif replace_firewall_file "$tmp" "$target"; then
            firewall_rc=0
            if [ -f "$backup" ] && ! cmp -s "$backup" "$target"; then
                printf 'Firewall backup for %s does not match the stock rules; kept the live rules without the agent block\n' "$target" >&2
            fi
        else
            firewall_rc=1
        fi
        rm -f "$tmp"
    elif [ -f "$backup" ] && [ ! -L "$backup" ]; then
        replace_firewall_file "$backup" "$target"
        firewall_rc=$?
    else
        firewall_rc=0
    fi
    remount_root_ro || firewall_rc=1
    return "$firewall_rc"
}

startup_entry_matches() {
    if [ -L "$1" ]; then
        [ -L "$2" ] || return 1
        readlink "$1" > "$REMOVE_WORK/link-before" || return 1
        readlink "$2" > "$REMOVE_WORK/link-after" || return 1
        cmp -s "$REMOVE_WORK/link-before" "$REMOVE_WORK/link-after" || return 1
    else
        [ -f "$1" ] && [ -f "$2" ] && [ ! -L "$2" ] || return 1
        cmp -s "$1" "$2" || return 1
    fi
    startup_meta_before="$(stat -c '%a:%u:%g' "$1")" || return 1
    startup_meta_after="$(stat -c '%a:%u:%g' "$2")" || return 1
    [ "$startup_meta_before" = "$startup_meta_after" ]
}

save_startup_entry() {
    if [ -L "$1" ] || [ -f "$1" ]; then
        cp -a "$1" "$2" && startup_entry_matches "$1" "$2"
    elif [ -e "$1" ]; then
        return 1
    else
        : > "$2.absent"
    fi
}

restore_startup_entry() {
    if [ -f "$1.absent" ]; then
        [ ! -e "$2" ] && [ ! -L "$2" ]
        return $?
    fi
    startup_entry_matches "$1" "$2" && return 0
    # Never follow a replacement symlink or overwrite a concurrent new entry.
    [ ! -e "$2" ] && [ ! -L "$2" ] || return 1
    RESTORE_STAGE="$(mktemp -d "${2}.c300x-startup.XXXXXX")" || return 1
    startup_restore_rc=0
    if ! cp -a "$1" "$RESTORE_STAGE/entry" \
        || ! startup_entry_matches "$1" "$RESTORE_STAGE/entry" \
        || ! mv -f "$RESTORE_STAGE/entry" "$2" \
        || ! startup_entry_matches "$1" "$2"; then
        startup_restore_rc=1
    fi
    if rm -rf "$RESTORE_STAGE"; then
        RESTORE_STAGE=""
    else
        startup_restore_rc=1
    fi
    return "$startup_restore_rc"
}

restore_startup() {
    remount_root_rw || return 1
    startup_rollback_rc=0
    restore_startup_entry "$REMOVE_WORK/startup/script" "$INIT_SCRIPT" || startup_rollback_rc=1
    restore_startup_entry "$REMOVE_WORK/startup/link" "$INIT_LINK" || startup_rollback_rc=1
    return "$startup_rollback_rc"
}

remove_startup() {
    mkdir "$REMOVE_WORK/startup" \
        && save_startup_entry "$INIT_SCRIPT" "$REMOVE_WORK/startup/script" \
        && save_startup_entry "$INIT_LINK" "$REMOVE_WORK/startup/link" || return 1
    remount_root_rw || return 1
    STARTUP_ACTIVE=1
    rm -f "$INIT_LINK" "$INIT_SCRIPT" || return 1
    # Also detect a command which reports success without removing both entries.
    [ ! -e "$INIT_LINK" ] && [ ! -L "$INIT_LINK" ] \
        && [ ! -e "$INIT_SCRIPT" ] && [ ! -L "$INIT_SCRIPT" ] || return 1
    if ! remount_root_ro; then
        STARTUP_RO_FAILED=1
        return 1
    fi
    return 0
}

agent_stopped() {
    agent_pids="$(pidof c300x-agent-native 2> "$REMOVE_WORK/agent-probe-error")"
    agent_probe_rc=$?
    [ ! -s "$REMOVE_WORK/agent-probe-error" ] || return 2
    case "$agent_probe_rc:$agent_pids" in
        1:) return 0 ;;
        0:?*) return 1 ;;
        *) return 2 ;;
    esac
}

stop_agent() {
    agent_stopped
    case $? in 0) return 0 ;; 1) ;; *) return 1 ;; esac
    # Match the process name, not a possibly stale PID file. TERM lets active
    # native transactions finish; never proceed on signal delivery alone.
    AGENT_STOPPED=1
    if ! killall c300x-agent-native >/dev/null 2>&1; then
        agent_stopped
        return $?
    fi
    stop_wait=10
    while :; do
        agent_stopped
        case $? in 0) return 0 ;; 1) ;; *) return 1 ;; esac
        [ "$stop_wait" -gt 0 ] || return 1
        sleep 1 || return 1
        stop_wait=$((stop_wait - 1))
    done
}

agent_tree_entry() {
    # Length-prefix paths/link targets so embedded newlines cannot alias entries.
    printf '%s:%s\n' "${#1}" "$1" || return 1
    stat -c '%f:%u:%g' "$1" || return 1
    if [ -L "$1" ]; then
        stat -c '%s' "$1" && readlink "$1"
    elif [ -f "$1" ]; then
        sha256sum < "$1"
    elif [ -d "$1" ]; then
        [ -r "$1" ] && [ -x "$1" ] || return 1
        for tree_entry in "$1"/* "$1"/.[!.]* "$1"/..?*; do
            [ -e "$tree_entry" ] || [ -L "$tree_entry" ] || continue
            agent_tree_entry "$tree_entry" || return 1
        done
    else
        return 1
    fi
}

agent_tree_manifest() {
    [ -d "$AGENT_DIR" ] && [ ! -L "$AGENT_DIR" ] \
        && [ -f "$AGENT_DIR/c300x-agent-native" ] \
        && [ -x "$AGENT_DIR/c300x-agent-native" ] \
        && [ ! -L "$AGENT_DIR/c300x-agent-native" ] || return 1
    agent_tree_entry "$AGENT_DIR"
}

agent_tree_unchanged() {
    agent_tree_manifest > "$REMOVE_WORK/agent-after-delete" \
        && cmp -s "$REMOVE_WORK/agent-before-delete" "$REMOVE_WORK/agent-after-delete"
}

restore_media_patches() {
    media_errors="$REMOVE_WORK/media-restore-errors"
    if ! media_result="$(C300X_AUDIO_BACKUP_DIR="$BACKUP_ROOT/original" \
        C300X_ROUTING_BACKUP_DIR="$BACKUP_ROOT/original/home/bticino/bin" \
        "$AGENT_DIR/c300x-agent-native" --restore-media-patches 2>"$media_errors")"; then
        cat "$media_errors" >&2
        if grep -F -q -x 'Failed to restore device routing: remount_ro_failed' "$media_errors"; then
            printf 'Root read-only remount failed after the routing restore; / may still be writable, perform a full device reboot before retrying removal\n' >&2
        fi
        printf 'Failed to restore media patches; keeping agent files and backups in place\n' >&2
        exit 1
    fi
    cat "$media_errors" >&2
    # The CLI emits this fixed JSON record only after verifying restoration.
    # Older agents returned no stdout. The pending flag explains a RO failure;
    # it never bypasses rollback or schedules a reboot before cleanup.
    case "$media_result" in
        '{"ok":true,"media_reboot_required":true}') MEDIA_REBOOT_REQUIRED=1 ;;
        '{"ok":true,"media_reboot_required":false}'|'') MEDIA_REBOOT_REQUIRED=0 ;;
        *)
            printf 'Invalid media restoration result; keeping agent files and backups in place\n' >&2
            exit 1 ;;
    esac
}

# Cover a display restored earlier with its library still changed. A running
# process may keep the replaced library open; later RO failures still abort
# removal and preserve startup entries, the agent and backups.
# Without a valid stock backup the library stays as it is (wider tap
# tolerance); any other failure keeps the backup for another removal.
restore_display_library() {
    [ -e "$C100X_MARKER" ] && return 0
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
if ! stop_agent; then
    printf 'Cannot verify agent termination; no restoration or deletion performed, keeping agent files and backups in place\n' >&2
    exit 1
fi
restore_qml
if ! restore_firewall "$IPTABLES6" "$IPTABLES6_BACKUP"; then
    printf 'Failed to restore IPv6 firewall patch; keeping agent files and backups in place\n' >&2
    exit 1
fi
if ! restore_firewall "$IPTABLES" "$IPTABLES_BACKUP"; then
    printf 'Failed to restore IPv4 firewall patch; keeping agent files and backups in place\n' >&2
    exit 1
fi
if ! restore_display_library; then
    printf 'Failed to restore the display library; keeping agent files and backups in place\n' >&2
    exit 1
fi
restore_media_patches
if ! agent_tree_manifest > "$REMOVE_WORK/agent-before-delete"; then
    printf 'Cannot record agent recovery identity; keeping startup, agent files and backups in place\n' >&2
    exit 1
fi
if ! remove_startup; then
    printf 'Failed to remove startup files; keeping agent files and backups in place\n' >&2
    exit 1
fi
FINAL_DELETE_STARTED=1
if ! rm -rf "$AGENT_DIR" "$BACKUP_ROOT" \
    || [ -e "$AGENT_DIR" ] || [ -L "$AGENT_DIR" ] \
    || [ -e "$BACKUP_ROOT" ] || [ -L "$BACKUP_ROOT" ]; then
    printf 'Failed to finish deleting agent files and backups\n' >&2
    exit 1
fi
STARTUP_ACTIVE=0
FINAL_DELETE_STARTED=0
start_ssh
schedule_reboot

exit 0
