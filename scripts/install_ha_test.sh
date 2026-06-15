#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT_DIR/custom_components/bticino_c300x"

discover_custom_components_dir() {
    local storage_dir
    local config_root
    while IFS= read -r storage_dir; do
        config_root="${storage_dir%/.storage}"
        if [[ -d "$config_root/custom_components" ]]; then
            printf '%s\n' "$config_root/custom_components"
            return
        fi
    done < <(
        find "/run/user/$(id -u)/gvfs" \
            -maxdepth 2 \
            -type d \
            -name '.storage' \
            -print 2>/dev/null
    )

    find "/run/user/$(id -u)/gvfs" \
        -maxdepth 2 \
        -path '*/custom_components' \
        -not -path '*/.codex-backups/*' \
        -not -path '*/config/custom_components' \
        -type d \
        -print \
        -quit 2>/dev/null || true
}

CUSTOM_COMPONENTS_DIR="${HA_TEST_CUSTOM_COMPONENTS_DIR:-$(discover_custom_components_dir)}"
TARGET_DIR="$CUSTOM_COMPONENTS_DIR/bticino_c300x"

target_uri_from_gvfs_path() {
    local path="$1"
    local prefix="/run/user/$(id -u)/gvfs/"
    local relative="${path#$prefix}"
    local mount_part="${relative%%/custom_components*}"
    case "$mount_part" in
        smb-share:server=*,share=*)
            local server="${mount_part#smb-share:server=}"
            server="${server%%,*}"
            local share="${mount_part##*,share=}"
            printf 'smb://%s/%s/custom_components/bticino_c300x\n' "$server" "$share"
            ;;
        *)
            return 1
            ;;
    esac
}

TARGET_URI="${HA_TEST_CUSTOM_COMPONENTS_URI:-$(target_uri_from_gvfs_path "$CUSTOM_COMPONENTS_DIR" 2>/dev/null || true)}"

usage() {
    cat <<'EOF'
Usage: scripts/install_ha_test.sh

Installs the local bticino_c300x custom component into the HA test
configuration exposed through the GVFS SMB config share.

Environment:
  HA_TEST_CUSTOM_COMPONENTS_DIR  Override the custom_components directory.
  HA_TEST_CUSTOM_COMPONENTS_URI  Override the GIO fallback URI.

Notes:
  - Does not use rsync because GVFS/SMB rejects rsync temp files.
  - Does not use hard-coded local Home Assistant config paths.
  - Copies files directly and removes only stale files below bticino_c300x
    when GVFS exposes normal directory operations.
  - Falls back to gio copy when GVFS can access files but not stat the
    component directory itself.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if [[ ! -d "$SOURCE_DIR" ]]; then
    printf 'Missing source directory: %s\n' "$SOURCE_DIR" >&2
    exit 1
fi

if [[ "${C300X_INSTALL_STAGE_AGENT_BUNDLE:-1}" == "1" ]]; then
    "$ROOT_DIR/scripts/stage_device_agent_bundle.py"
fi

if [[ -z "$CUSTOM_COMPONENTS_DIR" || ! -d "$CUSTOM_COMPONENTS_DIR" ]]; then
    printf 'Missing HA test custom_components directory: %s\n' "$CUSTOM_COMPONENTS_DIR" >&2
    printf 'Mount the HA test config SMB share first or set HA_TEST_CUSTOM_COMPONENTS_DIR.\n' >&2
    exit 1
fi

gio_copy_tree() {
    if ! command -v gio >/dev/null 2>&1; then
        printf 'gio is required for the GVFS fallback copier.\n' >&2
        exit 1
    fi
    if [[ -z "$TARGET_URI" ]]; then
        printf 'Cannot derive GIO target URI. Set HA_TEST_CUSTOM_COMPONENTS_URI.\n' >&2
        exit 1
    fi

    while IFS= read -r -d '' directory; do
        rel="${directory#$SOURCE_DIR/}"
        [[ "$rel" == "$directory" ]] && continue
        gio mkdir "$TARGET_URI/$rel" >/dev/null 2>&1 || true
    done < <(find "$SOURCE_DIR" -type d -not -name '__pycache__' -print0)

    while IFS= read -r -d '' file; do
        rel="${file#$SOURCE_DIR/}"
        case "$rel" in
            __pycache__/*|*/__pycache__/*) continue ;;
        esac
        gio copy -T "$file" "$TARGET_URI/$rel"
    done < <(find "$SOURCE_DIR" -type f -print0)

    if ! gio cat "$TARGET_URI/executor.py" | grep -F -q '_commands_with_alarmo_readiness'; then
        printf 'Installed executor.py does not contain the expected Alarmo readiness code.\n' >&2
        exit 1
    fi

    printf 'Installed HA test integration through GIO: %s\n' "$TARGET_URI"
}

direct_copy_tree() {
    if [[ -e "$TARGET_DIR" && ! -d "$TARGET_DIR" ]]; then
        printf 'Target exists but is not a directory: %s\n' "$TARGET_DIR" >&2
        exit 1
    fi

    if [[ -d "$TARGET_DIR" ]]; then
        if ! find "$TARGET_DIR" -maxdepth 0 -type d >/dev/null 2>&1; then
            return 2
        fi
    else
        mkdir -p "$TARGET_DIR" || return 2
    fi

    while IFS= read -r -d '' directory; do
        rel="${directory#$SOURCE_DIR/}"
        [[ "$rel" == "$directory" ]] && continue
        mkdir -p "$TARGET_DIR/$rel"
    done < <(find "$SOURCE_DIR" -type d -not -name '__pycache__' -print0)

    while IFS= read -r -d '' file; do
        rel="${file#$SOURCE_DIR/}"
        case "$rel" in
            __pycache__/*|*/__pycache__/*) continue ;;
        esac
        mkdir -p "$(dirname "$TARGET_DIR/$rel")"
        cp -f "$file" "$TARGET_DIR/$rel"
    done < <(find "$SOURCE_DIR" -type f -print0)

    if [[ "${C300X_INSTALL_PRUNE:-1}" == "1" ]]; then
        while IFS= read -r -d '' target_file; do
            rel="${target_file#$TARGET_DIR/}"
            if [[ ! -f "$SOURCE_DIR/$rel" ]]; then
                rm -f "$target_file"
            fi
        done < <(find "$TARGET_DIR" -type f -print0)

        find "$TARGET_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
        find "$TARGET_DIR" -depth -type d -empty -not -path "$TARGET_DIR" -delete
    fi

    if ! grep -F -q '_commands_with_alarmo_readiness' "$TARGET_DIR/executor.py"; then
        printf 'Installed executor.py does not contain the expected Alarmo readiness code.\n' >&2
        exit 1
    fi

    printf 'Installed HA test integration: %s\n' "$TARGET_DIR"
}

if ! direct_copy_tree; then
    printf 'Direct GVFS copy unavailable for %s; trying GIO file copy fallback.\n' "$TARGET_DIR" >&2
    gio_copy_tree
fi
