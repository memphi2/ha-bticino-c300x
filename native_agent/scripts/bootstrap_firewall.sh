#!/bin/sh
set -eu

PATH=/sbin:/usr/sbin:/bin:/usr/bin

IPTABLES="${C300X_IPTABLES:-/etc/network/if-pre-up.d/iptables}"
BACKUP="${C300X_IPTABLES_BACKUP:-/home/bticino/cfg/extra/c300x-device-file-backups/original/etc/network/if-pre-up.d/iptables}"
PORT="${C300X_API_PORT:-${1:-}}"
RTSP_PORT="${C300X_RTSP_PORT:-${2:-6554}}"
TALKBACK_RTP_PORT="${C300X_TALKBACK_RTP_PORT:-${3:-40004}}"
# A direct invocation has no merged HA config. On a C100X require an explicit
# opt-in for media; keep the historical C300X default.
if [ -e "${C300X_QML_C100X_MARKER:-/home/bticino/bin/gui/BtClass100}" ]; then
    VIDEO_ENABLED="${C300X_VIDEO_ENABLED:-0}"
else
    VIDEO_ENABLED="${C300X_VIDEO_ENABLED:-1}"
fi
BEGIN="# c300x-native-agent firewall begin"
END="# c300x-native-agent firewall end"
IPV6_BEGIN="# c300x-native-agent ipv6 firewall begin"
IPV6_END="# c300x-native-agent ipv6 firewall end"

validate_port() {
    label="$1"
    value="$2"
    case "$value" in
        ''|*[!0-9]*)
            printf 'invalid %s port\n' "$label" >&2
            exit 2
            ;;
    esac
    if [ "$value" -lt 1 ] || [ "$value" -gt 65535 ]; then
        printf 'invalid %s port\n' "$label" >&2
        exit 2
    fi
}

validate_port api "$PORT"
validate_port rtsp "$RTSP_PORT"
validate_port talkback "$TALKBACK_RTP_PORT"

apply_live_rules() {
    command -v iptables >/dev/null 2>&1 || return 0
    if ! iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null; then
        iptables -A INPUT -p tcp --dport "$PORT" -j ACCEPT
    fi
    if [ "$VIDEO_ENABLED" = "1" ]; then
        if ! iptables -C INPUT -p tcp --dport "$RTSP_PORT" -j ACCEPT 2>/dev/null; then
            iptables -A INPUT -p tcp --dport "$RTSP_PORT" -j ACCEPT
        fi
        if ! iptables -C INPUT -p udp --dport "$TALKBACK_RTP_PORT" -j ACCEPT 2>/dev/null; then
            iptables -A INPUT -p udp --dport "$TALKBACK_RTP_PORT" -j ACCEPT
        fi
    fi
}

TMP="/tmp/c300x-firewall.$$"
BASE="/tmp/c300x-firewall-base.$$"
ORIGINAL="/tmp/c300x-firewall-original.$$"
LIVE_TMP=""
BACKUP_TMP=""
ROOT_RW=0

cleanup() {
    rm -f "$TMP" "$BASE" "$ORIGINAL"
    if [ -n "$LIVE_TMP" ]; then
        rm -f "$LIVE_TMP"
    fi
    if [ -n "$BACKUP_TMP" ]; then
        rm -f "$BACKUP_TMP"
    fi
    if [ "$ROOT_RW" -eq 1 ]; then
        mount -o remount,ro /
    fi
}
trap cleanup EXIT

# Without a boot hook there is nothing to keep the rules across a reboot:
# open the ports for this run and write no file.
if [ ! -e "$IPTABLES" ] && [ ! -L "$IPTABLES" ]; then
    apply_live_rules
    printf 'changed_files=0\n'
    exit 0
fi
[ -f "$IPTABLES" ] || exit 1

awk -v begin="$BEGIN" -v end="$END" '
    $0 == begin {skip = 1; next}
    $0 == end {skip = 0; next}
    skip != 1 {print}
' "$IPTABLES" > "$BASE"

awk -v begin="$BEGIN" -v end="$END" -v ipv6_begin="$IPV6_BEGIN" -v ipv6_end="$IPV6_END" '
    $0 == begin {skip = 1; next}
    $0 == end {skip = 0; next}
    $0 == ipv6_begin {skip = 1; next}
    $0 == ipv6_end {skip = 0; next}
    skip != 1 {print}
' "$IPTABLES" > "$ORIGINAL"

cat "$BASE" > "$TMP"
if [ -s "$TMP" ] && [ "$(tail -c 1 "$TMP" 2>/dev/null)" != "" ]; then
    printf '\n' >> "$TMP"
fi

cat >> "$TMP" <<EOF
$BEGIN
# Managed by c300x-native-agent. Opens the configured API and media ports.
if command -v iptables >/dev/null 2>&1; then
    if ! iptables -C INPUT -p tcp --dport $PORT -j ACCEPT 2>/dev/null; then
        iptables -A INPUT -p tcp --dport $PORT -j ACCEPT
    fi
EOF
if [ "$VIDEO_ENABLED" = "1" ]; then
    cat >> "$TMP" <<EOF
    if ! iptables -C INPUT -p tcp --dport $RTSP_PORT -j ACCEPT 2>/dev/null; then
        iptables -A INPUT -p tcp --dport $RTSP_PORT -j ACCEPT
    fi
    if ! iptables -C INPUT -p udp --dport $TALKBACK_RTP_PORT -j ACCEPT 2>/dev/null; then
        iptables -A INPUT -p udp --dport $TALKBACK_RTP_PORT -j ACCEPT
    fi
EOF
fi
cat >> "$TMP" <<EOF
fi
$END
EOF

changed_files=0
if [ -e "$BACKUP" ] || [ -L "$BACKUP" ]; then
    # Older interrupted installs could leave a partial backup. Never trust it
    # without matching the unmanaged rules still present in the live script.
    if [ -L "$BACKUP" ] || [ ! -f "$BACKUP" ] || ! cmp -s "$ORIGINAL" "$BACKUP"; then
        printf 'existing firewall backup cannot be verified\n' >&2
        exit 1
    fi
fi
if ! cmp -s "$IPTABLES" "$TMP"; then
    if [ ! -f "$BACKUP" ]; then
        mkdir -p "$(dirname "$BACKUP")"
        BACKUP_TMP="$(mktemp "${BACKUP}.c300x.XXXXXX")"
        cp "$ORIGINAL" "$BACKUP_TMP"
        chmod 600 "$BACKUP_TMP"
        cmp -s "$ORIGINAL" "$BACKUP_TMP"
        mv -f "$BACKUP_TMP" "$BACKUP"
        BACKUP_TMP=""
        changed_files=$((changed_files + 1))
    fi
    mount -o remount,rw /
    ROOT_RW=1
    LIVE_TMP="$(mktemp "${IPTABLES}.c300x.XXXXXX")"
    write_rc=0
    # Keep the live startup script intact until all bytes and metadata are ready.
    cp -p "$IPTABLES" "$LIVE_TMP" &&
        cat "$TMP" > "$LIVE_TMP" &&
        cmp -s "$TMP" "$LIVE_TMP" &&
        mv -f "$LIVE_TMP" "$IPTABLES" || write_rc=$?
    rm -f "$LIVE_TMP"
    LIVE_TMP=""
    mount -o remount,ro /
    ROOT_RW=0
    if [ "$write_rc" -ne 0 ]; then
        exit "$write_rc"
    fi
    changed_files=$((changed_files + 1))
fi

apply_live_rules
printf 'changed_files=%s\n' "$changed_files"
