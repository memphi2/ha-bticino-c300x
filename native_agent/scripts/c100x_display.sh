#!/bin/sh
# C100X-only disk transaction. No GUI signals, supervisor changes or reboot.
set -eu
umask 077
ACTION=${1:-status}
AGENT=${C300X_AGENT_DIR:-/home/bticino/cfg/extra/c300x-native-agent}
GUI=${C100X_GUI_DIR:-/home/bticino/bin/gui/skins/default}
SOURCE=${C100X_SOURCE_DIR:-$AGENT/qml/c100x}
BACKUP=${C100X_BACKUP_DIR:-/home/bticino/cfg/extra/c300x-device-file-backups/c100x-display}
BIN=${C100X_GUI_BIN:-/home/bticino/bin/gui/BtClass100}
WRAPPER=${C100X_GUI_WRAPPER:-/home/bticino/bin/BtClass100_qws}
TRANSFORM=${C100X_HOOKS_AWK:-$AGENT/c100x_hooks.awk}
IDENTITY=${C100X_IDENTITY_SCRIPT:-$AGENT/c100x_display_identity.sh}
TRIAL=${C100X_TRIAL_SCRIPT:-$AGENT/c100x_display_trial.sh}
PREPARE=0
if [ "$ACTION" = prepare ]; then ACTION=apply; PREPARE=1; fi
MAIN_SHA=ff1740e9742951f5cda2225d605eae06141f43ee26d900ca21d7fdf14960e6fb
MENU_SHA=ba3edae9b9e670dad86894f93747f510f07c2389f498697e5d20dd95b4cb8e80
WORK=
STAGE=
DIRTY=0
RW=0

fail() { printf '%s\n' "c100x_display: $1" >&2; exit 1; }
regular() { [ -f "$1" ] && [ ! -L "$1" ] && [ "$(stat -c %h "$1")" = 1 ]; }
hash() { sha256sum "$1" | awk '{print $1}'; }
identity() { regular "$1" && [ "$(hash "$1")" = "$2" ]; }
safe_path() {
    case "$1" in /*) ;; *) return 1 ;; esac
    case "$1" in *'/../'*|*'/./'*|*/..|*/.|*'//'*) return 1 ;; esac
    check=$1
    while [ "$check" != / ]; do
        [ ! -L "$check" ] || return 1
        check=${check%/*}
        [ -n "$check" ] || check=/
    done
}
originals() { identity "$1/main.qml" "$MAIN_SHA" && identity "$1/MainPage.qml" "$MENU_SHA"; }
valid_manifest() {
    regular "$1" || return 1
    awk 'NF != 2 || length($1) != 64 || $1 !~ /^[0-9a-f]+$/ ||
         $2 !~ /^((js|hooks)\/)?[A-Za-z0-9_]+\.(qml|js|inc)$/ || seen[$2]++ {exit 1}
         END {if (NR < 20) exit 1}' "$1"
}
verify_tree() {
    safe_path "$1" && valid_manifest "$1/SHA256SUMS" || return 1
    while read -r digest relative; do
        safe_path "$1/$relative" && identity "$1/$relative" "$digest" || return 1
    done < "$1/SHA256SUMS"
    # Reject unmanifested files and any symlink (including directory symlinks).
    [ -z "$(find "$1" ! -type d ! -type f -print)" ] || return 1
    expected=$(wc -l < "$1/SHA256SUMS")
    actual=$(find "$1" -type f | wc -l)
    [ "$actual" -eq "$((expected + 1))" ]
}
remount_rw() {
    if [ "${C100X_NO_REMOUNT:-0}" != 1 ]; then mount -o remount,rw / || return 1; fi
    RW=1
}
remount_ro() {
    [ "$RW" = 1 ] || return 0
    if [ "${C100X_NO_REMOUNT:-0}" != 1 ]; then mount -o remount,ro / || return 1; fi
    RW=0
}
replace() {
    if cmp -s "$1" "$2" && [ "$(stat -c %a "$1")" = "$(stat -c %a "$2")" ]; then return 0; fi
    cp -p "$1" "$STAGE/replace" && identity "$STAGE/replace" "$(hash "$1")" && sync && mv -f "$STAGE/replace" "$2" && sync
}
restore_originals() {
    originals "$BACKUP" || return 1
    # main is the switch: disable the bridge before removing its menu entry.
    replace "$BACKUP/main.qml" "$GUI/main.qml" && replace "$BACKUP/MainPage.qml" "$GUI/MainPage.qml" && originals "$GUI"
}
rollback_previous() {
    replace "$WORK/before/MainPage.qml" "$GUI/MainPage.qml" && replace "$WORK/before/main.qml" "$GUI/main.qml"
}
cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    if [ "$result" != 0 ] && [ "$DIRTY" = 1 ]; then
        if remount_rw && rollback_previous; then sync; else printf '%s\n' 'c100x_display: rollback failed; backups retained' >&2; fi
    fi
    if [ -n "$STAGE" ]; then rm -rf "$STAGE"; fi
    if [ -n "$WORK" ]; then rm -rf "$WORK"; fi
    if ! remount_ro; then result=1; fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
case "$ACTION" in status|apply|restore|recover|confirm|boot) ;; *) fail 'unsupported action' ;; esac
for path in "$GUI" "$BACKUP" "$BIN" "$WRAPPER" "$IDENTITY"; do
    safe_path "$path" || fail 'unsafe path'
done
identity "$BIN" 84e3f9fa36a4a3abffe39dd46b10b47074c6144287a2cd0f63bcce622770c3dc || fail 'unsupported GUI binary'
identity "$WRAPPER" ad6d23db69795afb712751b3d92afbca3356d524b40bdb441de096b3d12c3612 || fail 'unsupported GUI wrapper'
identity "$GUI/EventManager.qml" 3ca4b5e8c27c8c8b283d533106091072e25632bb090d414ee4c1d93f3a06b181 || fail 'unsupported event manager'
regular "$IDENTITY" || fail 'identity helper unavailable'
. "$IDENTITY"
safe_path "$TRIAL" && regular "$TRIAL" || fail 'trial helper unavailable'
. "$TRIAL"
RESULT=interrupted
if [ "$ACTION" = boot ]; then
    # Start rule: keep the trial in its own boots, roll it back in any later one.
    boot_phase
    case "$TRIAL_PHASE" in
        none|prepare|trial) exit 0 ;;
        first) write_marker pending.trial-boot "$CURRENT_BOOT" || fail 'trial boot mark failed'; exit 0 ;;
        later) RESULT=rolled_back ;;
    esac
    ACTION=recover
fi
if trial_exists && [ "$ACTION" = apply ]; then fail 'pending trial requires confirmation or recovery'; fi
if [ "$ACTION" != apply ] && [ "$ACTION" != confirm ] && ! trial_exists && originals "$GUI"; then
    printf '%s\n' '{"ok":true,"state":"stock","runtime_verified":false}'
    exit 0
fi
if [ "$ACTION" = apply ]; then
    verify_tree "$SOURCE" || fail 'invalid adapter source'
    RELEASE=.c100x-$(hash "$SOURCE/SHA256SUMS")
fi
if [ "$ACTION" != status ]; then
    # Lock the verified immutable vendor inode read-only, before any remount.
    # A competing caller must never remount the first caller's transaction RO.
    exec 9<"$BIN"
    flock -n 9 || fail 'transaction busy'
    remount_rw || fail 'root read-write remount failed'
    mkdir -p "$BACKUP" || fail 'backup directory unavailable'
    safe_path "$BACKUP" && [ -d "$BACKUP" ] || fail 'unsafe backup directory'
fi
WORK=$(mktemp -d "${TMPDIR:-/tmp}/c100x-display.XXXXXX") || fail 'private work directory unavailable'
if [ "$ACTION" != status ]; then
    for file in main.qml MainPage.qml; do
        if [ ! -e "$BACKUP/$file" ] && [ ! -L "$BACKUP/$file" ]; then
            case "$file" in main.qml) expected=$MAIN_SHA ;; *) expected=$MENU_SHA ;; esac
            identity "$GUI/$file" "$expected" || fail 'original backup missing'
            # Stage on the backup filesystem, so even power loss cannot publish a partial backup.
            backup_stage=$(mktemp -d "$BACKUP/stage.XXXXXX") || fail 'backup stage unavailable'
            cp -p "$GUI/$file" "$backup_stage/$file"
            identity "$backup_stage/$file" "$expected" || fail 'backup verification failed'
            mv "$backup_stage/$file" "$BACKUP/$file"
            rmdir "$backup_stage"
        fi
    done
fi
originals "$BACKUP" || fail 'invalid original backup'
if [ "$ACTION" != status ]; then sync; fi
if [ "$ACTION" = apply ]; then
    archive_generation "$SOURCE" "$RELEASE" || fail 'invalid generation recipe'
    render_generation "$BACKUP/generations/$RELEASE" "$RELEASE" "$WORK/new" || fail 'generation rendering failed'
    if [ -e "$GUI/$RELEASE" ] || [ -L "$GUI/$RELEASE" ]; then
        verify_tree "$GUI/$RELEASE" && cmp -s "$BACKUP/generations/$RELEASE/SHA256SUMS" "$GUI/$RELEASE/SHA256SUMS" || fail 'invalid installed adapter'
    fi
fi
verify_current || fail 'unknown target identity'
if [ "$ACTION" = status ]; then
    if [ -n "$ACTIVE_RELEASE" ] && cmp -s "$GUI/MainPage.qml" "$WORK/check/MainPage.qml" && verify_tree "$GUI/$ACTIVE_RELEASE"; then
        printf '%s\n' '{"ok":true,"state":"installed","runtime_verified":false}'
    else
        printf '%s\n' '{"ok":true,"state":"partial","runtime_verified":false}'
    fi
    exit 0
fi
mkdir "$WORK/before"
cp -p "$GUI/main.qml" "$GUI/MainPage.qml" "$WORK/before/"
verify_current || fail 'target changed before transaction'
cmp -s "$GUI/main.qml" "$WORK/before/main.qml" && cmp -s "$GUI/MainPage.qml" "$WORK/before/MainPage.qml" || fail 'target changed during snapshot'
STAGE=$(mktemp -d "$GUI/.c100x-stage.XXXXXX") || fail 'private GUI stage unavailable'
if [ "$ACTION" = confirm ]; then
    verify_trial || fail 'invalid pending trial'
    if confirm_trial; then
        remount_rw && archive_trial || fail 'trial confirmation archive failed; recovery retained'
        remount_ro || fail 'trial confirmed; read-only remount failed'
        printf '%s\n' '{"ok":true,"runtime_verified":true,"backups_retained":true}'
        exit 0
    fi
    remount_rw || fail 'rollback remount failed'
    DIRTY=1
    rollback_trial || fail 'readiness failed and rollback failed; recovery retained'
    DIRTY=0
    remount_ro || fail 'rollback read-only remount failed'
    fail 'readiness failed; prior files restored; GUI runtime requires recovery'
fi
if [ "$ACTION" = recover ] && trial_exists; then
    DIRTY=1
    rollback_trial || fail 'pending trial recovery failed'
    note_result "$RESULT" "$TRIAL_RELEASE"
    sync
    remount_ro || fail 'recovery read-only remount failed'
    DIRTY=0
    printf '%s\n' '{"ok":true,"runtime_verified":false,"trial_rolled_back":true,"backups_retained":true}'
    exit 0
fi
if [ "$ACTION" = apply ]; then
    if [ ! -d "$GUI/$RELEASE" ]; then
        mkdir "$STAGE/payload"
        while read -r digest relative; do
            mkdir -p "$STAGE/payload/$(dirname "$relative")"
            cp "$SOURCE/$relative" "$STAGE/payload/$relative"
            chmod 644 "$STAGE/payload/$relative"
        done < "$BACKUP/generations/$RELEASE/SHA256SUMS"
        cp "$BACKUP/generations/$RELEASE/SHA256SUMS" "$STAGE/payload/SHA256SUMS"
        find "$STAGE/payload" -type d -exec chmod 755 {} \;
        verify_tree "$STAGE/payload" && identity "$STAGE/payload/SHA256SUMS" "${RELEASE#.c100x-}" || fail 'staged adapter verification failed'
        mv "$STAGE/payload" "$GUI/$RELEASE"
        sync
    fi
    if [ "$PREPARE" = 1 ]; then prepare_trial || fail 'activation snapshot failed'; fi
    DIRTY=1
    replace "$WORK/new/MainPage.qml" "$GUI/MainPage.qml" || fail 'menu replacement failed'
    replace "$WORK/new/main.qml" "$GUI/main.qml" || fail 'main replacement failed'
    cmp -s "$WORK/new/main.qml" "$GUI/main.qml" && cmp -s "$WORK/new/MainPage.qml" "$GUI/MainPage.qml" || fail 'commit verification failed'
else
    DIRTY=1
    restore_originals || fail 'original restoration failed'
    originals "$GUI" || fail 'restore verification failed'
    if trial_exists; then
        DIRTY=0
        archive_trial || fail 'trial archive failed; originals restored'
    fi
fi
sync
remount_ro || fail 'root read-only remount failed'
DIRTY=0
printf '%s\n' '{"ok":true,"runtime_verified":false,"backups_retained":true}'
