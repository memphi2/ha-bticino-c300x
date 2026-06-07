#!/bin/sh
set -eu

PATH=/sbin:/usr/sbin:/bin:/usr/bin

IPTABLES="${C300X_IPTABLES:-/etc/network/if-pre-up.d/iptables}"
BACKUP="${C300X_IPTABLES_BACKUP:-/home/bticino/cfg/extra/c300x-device-file-backups/original/etc/network/if-pre-up.d/iptables}"
PORT="${C300X_API_PORT:-${1:-}}"
RTSP_PORT="${C300X_RTSP_PORT:-${2:-6554}}"
TALKBACK_RTP_PORT="${C300X_TALKBACK_RTP_PORT:-${3:-40004}}"
VIDEO_ENABLED="${C300X_VIDEO_ENABLED:-1}"
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

TMP="/tmp/c300x-firewall.$$"
BASE="/tmp/c300x-firewall-base.$$"
ORIGINAL="/tmp/c300x-firewall-original.$$"

cleanup() {
    rm -f "$TMP" "$BASE" "$ORIGINAL"
}
trap cleanup EXIT

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
if ! cmp -s "$IPTABLES" "$TMP"; then
    if [ ! -f "$BACKUP" ]; then
        mkdir -p "$(dirname "$BACKUP")"
        cp "$ORIGINAL" "$BACKUP"
        chmod 600 "$BACKUP" >/dev/null 2>&1 || true
        changed_files=$((changed_files + 1))
    fi
    mount -o remount,rw /
    write_rc=0
    cat "$TMP" > "$IPTABLES" || write_rc=$?
    if [ "$write_rc" -eq 0 ]; then
        chmod 755 "$IPTABLES" >/dev/null 2>&1 || true
    fi
    mount -o remount,ro /
    if [ "$write_rc" -ne 0 ]; then
        exit "$write_rc"
    fi
    changed_files=$((changed_files + 1))
fi

if command -v iptables >/dev/null 2>&1; then
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
fi

printf 'changed_files=%s\n' "$changed_files"
