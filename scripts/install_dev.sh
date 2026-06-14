#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_HA=1
INSTALL_DEVICE=1
APPLY_QML=1
UPLOAD_AGENT=0

usage() {
    cat <<'EOF'
Usage: scripts/install_dev.sh [options]

Installs the current local development state to HA test and the C300X.

Options:
  --ha-only        Install only the HA custom integration.
  --device-only    Install only C300X device files.
  --no-qml-apply   Upload display sources but do not apply/reload the Display patch.
  --agent          Build and upload the native ARMHF agent binary too.

Defaults:
  - HA install uses the GVFS SMB config share.
  - Device install uploads project-owned display files and qml_patch.sh.
  - The active C300X Display patch is applied once.
  - Device config.json is never overwritten.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ha-only)
            INSTALL_DEVICE=0
            shift
            ;;
        --device-only)
            INSTALL_HA=0
            shift
            ;;
        --no-qml-apply)
            APPLY_QML=0
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

if [[ "$INSTALL_HA" == "1" ]]; then
    "$ROOT_DIR/scripts/install_ha_test.sh"
fi

if [[ "$INSTALL_DEVICE" == "1" ]]; then
    device_args=()
    [[ "$APPLY_QML" == "1" ]] && device_args+=(--apply-qml)
    [[ "$UPLOAD_AGENT" == "1" ]] && device_args+=(--agent)
    "$ROOT_DIR/scripts/install_c300x_device.sh" "${device_args[@]}"
fi
