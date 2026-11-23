#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_DIR="${C300X_AGENT_DIR:-/home/bticino/cfg/extra/c300x-native-agent}"
PACKAGED_AGENT_BINARY="$ROOT_DIR/custom_components/bticino_c300x/device_agent/armhf/c300x-agent-native"
PACKAGED_BUNDLE_MANIFEST="$ROOT_DIR/custom_components/bticino_c300x/device_agent/bundle.json"
PACKAGED_INIT_SCRIPT="$ROOT_DIR/custom_components/bticino_c300x/device_agent/init/c300x-native-agent"
SCRIPT_SOURCE_DIR="$ROOT_DIR/native_agent/scripts"
APPLY_QML=0
UPLOAD_AGENT=0

usage() {
    cat <<'EOF'
Usage: scripts/install_c300x_device.sh [--apply-qml] [--agent]

Installs project-owned C300X device files through password SSH/SCP.

Environment:
  C300X_HOST       Required device host.
  C300X_USER       Required SSH user.
  C300X_PASSWORD   Required SSH password.
  C300X_AGENT_DIR  Optional target directory.

Options:
  --apply-qml      Run the installed qml_patch.sh apply action once.
  --agent          Also build and upload the packaged native ARMHF agent binary.

Notes:
  - Uses scp -O because the C300X firmware does not provide SFTP.
  - Does not overwrite the device config.json.
  - qml_patch.sh writes active GUI files only when generated content differs.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply-qml)
            APPLY_QML=1
            shift
            ;;
        --agent)
            UPLOAD_AGENT=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

for name in C300X_HOST C300X_USER C300X_PASSWORD; do
    if [[ -z "${!name:-}" ]]; then
        printf 'Missing required environment variable: %s\n' "$name" >&2
        exit 1
    fi
done

if [[ ! "$REMOTE_DIR" =~ ^/[A-Za-z0-9_./-]+$ || "/$REMOTE_DIR/" == *"/../"* ]]; then
    printf 'Invalid C300X_AGENT_DIR. Use an absolute path without shell characters or traversal.\n' >&2
    exit 1
fi

if ! command -v sshpass >/dev/null 2>&1; then
    printf 'sshpass is required for C300X password SSH installs.\n' >&2
    exit 1
fi

SSH_OPTS=(
    -o HostKeyAlgorithms=+ssh-rsa
    -o PubkeyAcceptedAlgorithms=+ssh-rsa
    -o StrictHostKeyChecking=no
    -o UserKnownHostsFile=/dev/null
    -o LogLevel=ERROR
)
REMOTE="${C300X_USER}@${C300X_HOST}"
export SSHPASS="$C300X_PASSWORD"

ssh_cmd() {
    sshpass -e ssh "${SSH_OPTS[@]}" "$REMOTE" "$@"
}

scp_cmd() {
    sshpass -e scp -O -p "${SSH_OPTS[@]}" "$@"
}

install_startup_script() {
    scp_cmd "$PACKAGED_INIT_SCRIPT" "$REMOTE:$REMOTE_DIR/.c300x-native-agent-init.new"
    ssh_cmd "sh -s -- '$REMOTE_DIR'" <<'STARTUP_SCRIPT'
set -eu
umask 077
agent_dir=$1
source="$agent_dir/.c300x-native-agent-init.new"
rendered="$source.rendered"
env_file="$agent_dir/c300x-agent.env"
init=/etc/init.d/c300x-native-agent
link=/etc/rc5.d/S40c300x-native-agent
root_writable=0
cleanup() {
    rc=$?
    trap - EXIT
    rm -f "$source" "$rendered" "$env_file.new" || rc=1
    if [ "$root_writable" = 1 ]; then
        rm -f "$init.new" "$link.new" || rc=1
        mount -o remount,ro / || rc=1
    fi
    exit "$rc"
}
trap cleanup EXIT
grep -F -x 'DEFAULT_AGENT_DIR="/home/bticino/cfg/extra/c300x-native-agent"' "$source" >/dev/null
sed "s|^DEFAULT_AGENT_DIR=.*|DEFAULT_AGENT_DIR=\"$agent_dir\"|" "$source" > "$rendered"
sh -n "$rendered"
# Keep the same custom-directory contract as the HA installer and self-updater.
printf "C300X_AGENT_DIR='%s'\n" "$agent_dir" > "$env_file.new"
if ! cmp -s "$env_file.new" "$env_file"; then
    chmod 644 "$env_file.new"
    mv -f "$env_file.new" "$env_file"
fi
# Refuse unexpected target types before remounting or replacing startup files.
if [ -L "$init" ] || { [ -e "$init" ] && [ ! -f "$init" ]; }; then
    exit 1
fi
if [ -d "$link" ] || { [ -e "$link" ] && [ ! -L "$link" ] && [ ! -f "$link" ]; }; then
    exit 1
fi
if cmp -s "$rendered" "$init" && [ -x "$init" ] \
    && [ "$(readlink "$link")" = "$init" ]; then
    exit 0
fi
mount -o remount,rw /
root_writable=1
# Rename on the destination filesystem; never truncate the active init script.
rm -f "$init.new" "$link.new"
cp "$rendered" "$init.new"
chmod 700 "$init.new"
ln -s "$init" "$link.new"
mv -f "$init.new" "$init"
mv -f "$link.new" "$link"
STARTUP_SCRIPT
}

if [[ "$UPLOAD_AGENT" == "1" ]]; then
    make -C "$ROOT_DIR/native_agent" armhf armhf-abi-check
    "$ROOT_DIR/scripts/stage_device_agent_bundle.py" --skip-build
    QML_STAGE_DIR="$ROOT_DIR/custom_components/bticino_c300x/device_agent/qml"
    SCRIPT_SOURCE_DIR="$ROOT_DIR/custom_components/bticino_c300x/device_agent/scripts"
else
    QML_STAGE_DIR="$(mktemp -d)"
    trap 'rm -rf "$QML_STAGE_DIR"' EXIT
    "$ROOT_DIR/scripts/device_file_strip.py" --out "$QML_STAGE_DIR" >/dev/null
fi

ssh_cmd "mkdir -p '$REMOTE_DIR/qml/js'"

scp_cmd \
    "$QML_STAGE_DIR/Alarm.qml" \
    "$QML_STAGE_DIR/HomeAssistant.qml" \
    "$QML_STAGE_DIR/C300XEnergy.qml" \
    "$QML_STAGE_DIR/C300XEnergyConsumers.qml" \
    "$QML_STAGE_DIR/C300XPageNavigation.qml" \
    "$QML_STAGE_DIR/C300XAlerts.qml" \
    "$QML_STAGE_DIR/C300XAgenda.qml" \
    "$QML_STAGE_DIR/C300XLeaveHome.qml" \
    "$QML_STAGE_DIR/C300XChecks.qml" \
    "$QML_STAGE_DIR/C300XSituations.qml" \
    "$QML_STAGE_DIR/C300XOptionalPages.qml" \
    "$QML_STAGE_DIR/C300XDetailControl.qml" \
    "$QML_STAGE_DIR/C300XEnergyReadout.qml" \
    "$QML_STAGE_DIR/C300XEnergySums.qml" \
    "$QML_STAGE_DIR/C300XRingerControl.qml" \
    "$REMOTE:$REMOTE_DIR/qml/"

scp_cmd \
    "$QML_STAGE_DIR/js/c300x_alerts.js" \
    "$QML_STAGE_DIR/js/c300x_ringer.js" \
    "$QML_STAGE_DIR/js/c300x_energy.js" \
    "$QML_STAGE_DIR/js/c300x_energy_consumers.js" \
    "$QML_STAGE_DIR/js/c300x_ha.js" \
    "$QML_STAGE_DIR/js/c300x_i18n.js" \
    "$QML_STAGE_DIR/js/c300x_memos.js" \
    "$REMOTE:$REMOTE_DIR/qml/js/"

# Unpackaged development installs use the patch template and its source files.
if [[ "$UPLOAD_AGENT" == "0" ]]; then
    scp_cmd "$QML_STAGE_DIR/C300XSettings.qml" "$REMOTE:$REMOTE_DIR/qml/"
    scp_cmd "$QML_STAGE_DIR/js/c300x_maintenance.js" "$REMOTE:$REMOTE_DIR/qml/js/"
fi
scp_cmd "$SCRIPT_SOURCE_DIR/qml_patch.sh" "$REMOTE:$REMOTE_DIR/qml_patch.sh"
ssh_cmd "chmod 700 '$REMOTE_DIR/qml_patch.sh'"

scp_cmd "$SCRIPT_SOURCE_DIR/remove_agent.sh" "$REMOTE:$REMOTE_DIR/remove_agent.sh"
ssh_cmd "chmod 700 '$REMOTE_DIR/remove_agent.sh'"

scp_cmd "$SCRIPT_SOURCE_DIR/bootstrap_firewall.sh" "$REMOTE:$REMOTE_DIR/bootstrap_firewall.sh"
ssh_cmd "chmod 700 '$REMOTE_DIR/bootstrap_firewall.sh'"

if [[ "$UPLOAD_AGENT" == "1" ]]; then
    remote_agent_tmp="$REMOTE_DIR/.c300x-agent-native.new"
    scp_cmd \
        "$PACKAGED_AGENT_BINARY" \
        "$REMOTE:$remote_agent_tmp"
    ssh_cmd "chmod 700 '$remote_agent_tmp' && mv -f '$remote_agent_tmp' '$REMOTE_DIR/c300x-agent-native'"
    install_startup_script
fi

if [[ "$APPLY_QML" == "1" ]]; then
    qml_result="$(ssh_cmd "C300X_AGENT_DIR='$REMOTE_DIR' C300X_QML_SOURCE_DIR='$REMOTE_DIR/qml' '$REMOTE_DIR/qml_patch.sh' apply")"
    # The device can exit zero while reporting a failed GUI reload in JSON.
    python3 -c '
import json
import sys

try:
    result = json.load(sys.stdin)
except (ValueError, UnicodeError):
    result = None
if not isinstance(result, dict) or not all(
    result.get(key) is True for key in ("ok", "patched", "core_patched", "gui_running")
):
    sys.exit("QML patch verification failed; bundle manifest was not updated")
' <<<"$qml_result"
    printf '%s\n' "$qml_result"
fi

if [[ "$UPLOAD_AGENT" == "1" ]]; then
    # A partial install must keep the old hash so HA still offers its repair.
    remote_bundle_tmp="$REMOTE_DIR/.bundle.json.new"
    scp_cmd "$PACKAGED_BUNDLE_MANIFEST" "$REMOTE:$remote_bundle_tmp"
    ssh_cmd "chmod 600 '$remote_bundle_tmp' && mv -f '$remote_bundle_tmp' '$REMOTE_DIR/bundle.json'"
fi

# Retire only this generated source after uploads, optional patch and manifest.
ssh_cmd "if [ -L '$REMOTE_DIR/qml' ] || [ -L '$REMOTE_DIR/qml/C300XEnergyDistribution.qml' ] || { [ -e '$REMOTE_DIR/qml/C300XEnergyDistribution.qml' ] && [ ! -f '$REMOTE_DIR/qml/C300XEnergyDistribution.qml' ]; }; then exit 1; fi; if [ -f '$REMOTE_DIR/qml/C300XEnergyDistribution.qml' ]; then rm -f '$REMOTE_DIR/qml/C300XEnergyDistribution.qml'; fi"

printf 'Installed C300X device files in %s\n' "$REMOTE_DIR"
