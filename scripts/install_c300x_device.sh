#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_DIR="${C300X_AGENT_DIR:-/home/bticino/cfg/extra/c300x-native-agent}"
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
  --agent          Also build and upload the native ARMHF agent binary.

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

if [[ "$UPLOAD_AGENT" == "1" ]]; then
    make -C "$ROOT_DIR/native_agent" armhf
fi

ssh_cmd "mkdir -p '$REMOTE_DIR/qml/js'"

scp_cmd \
    "$ROOT_DIR/device_qml/Alarm.qml" \
    "$ROOT_DIR/device_qml/HomeAssistant.qml" \
    "$REMOTE:$REMOTE_DIR/qml/"

scp_cmd \
    "$ROOT_DIR/device_qml/js/c300x_ha.js" \
    "$ROOT_DIR/device_qml/js/c300x_i18n.js" \
    "$ROOT_DIR/device_qml/js/c300x_memos.js" \
    "$REMOTE:$REMOTE_DIR/qml/js/"

scp_cmd "$ROOT_DIR/native_agent/scripts/qml_patch.sh" "$REMOTE:$REMOTE_DIR/qml_patch.sh"
ssh_cmd "chmod 700 '$REMOTE_DIR/qml_patch.sh'"

scp_cmd "$ROOT_DIR/native_agent/scripts/remove_agent.sh" "$REMOTE:$REMOTE_DIR/remove_agent.sh"
ssh_cmd "chmod 700 '$REMOTE_DIR/remove_agent.sh'"

if [[ "$UPLOAD_AGENT" == "1" ]]; then
    remote_agent_tmp="$REMOTE_DIR/.c300x-agent-native.new"
    scp_cmd \
        "$ROOT_DIR/native_agent/build/armhf/c300x-agent-native" \
        "$REMOTE:$remote_agent_tmp"
    ssh_cmd "chmod 700 '$remote_agent_tmp' && mv -f '$remote_agent_tmp' '$REMOTE_DIR/c300x-agent-native'"
fi

if [[ "$APPLY_QML" == "1" ]]; then
    ssh_cmd "C300X_QML_SOURCE_DIR='$REMOTE_DIR/qml' '$REMOTE_DIR/qml_patch.sh' apply"
fi

printf 'Installed C300X device files in %s\n' "$REMOTE_DIR"
