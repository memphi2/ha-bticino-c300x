# Sourced by c100x_display.sh. Only these reviewed hook recipes may identify a
# modified stock file; an editable manifest alone never authorizes QML changes.
MAIN_HOOK_SHA=3c2b1bfcae4cea8fa4a901f3cc9133d64250931ae346423137cbda72851529ad
LEGACY_MAIN_HOOK_SHA=e69c0dc115759e4b1593fd324e8619ff516d66f5aa3fcc6e459417cc9bbdcd5b
MENU_HOOK_SHA=eb832ca9fa5f70d8904033a06303e9be5139a70c07822aad0b088635a437e8be
TRANSFORM_SHA=58edba48f6ca4efd0cafbb66b9d200a82336e82d52d9b33ec632ed02f39c4832

valid_release() {
    case "$1" in .c100x-*) ;; *) return 1 ;; esac
    [ "${#1}" = 71 ] || return 1
    case "${1#.c100x-}" in *[!0-9a-f]*) return 1 ;; esac
}
known_main_hook() {
    regular "$1" || return 1
    VERIFIED_MAIN_SHA=$(hash "$1")
    case "$VERIFIED_MAIN_SHA" in "$MAIN_HOOK_SHA"|"$LEGACY_MAIN_HOOK_SHA") return 0 ;; *) return 1 ;; esac
}
valid_recipe() {
    safe_path "$1" && known_main_hook "$1/main.inc" \
        && identity "$1/menu.inc" "$MENU_HOOK_SHA" && identity "$1/transform.awk" "$TRANSFORM_SHA"
}
valid_generation() {
    valid_release "$2" && valid_recipe "$1" \
        && identity "$1/SHA256SUMS" "${2#.c100x-}" && valid_manifest "$1/SHA256SUMS" || return 1
    awk -v main="$VERIFIED_MAIN_SHA" -v menu="$MENU_HOOK_SHA" '
        $1 == main && $2 == "hooks/main.inc" {m++}
        $1 == menu && $2 == "hooks/menu.inc" {n++}
        END {if (m != 1 || n != 1) exit 1}' "$1/SHA256SUMS"
}
render_generation() {
    valid_generation "$1" "$2" || return 1
    mkdir -p "$3" || return 1
    for render_file in main.qml MainPage.qml; do
        case "$render_file" in main.qml) render_mode=main ;; *) render_mode=menu ;; esac
        cp -p "$BACKUP/$render_file" "$3/$render_file" || return 1
        awk -v mode="$render_mode" -v hooks="$1" -v release="$2" -f "$1/transform.awk" \
            "$BACKUP/$render_file" > "$3/generated" || return 1
        cat "$3/generated" > "$3/$render_file" || return 1
    done
}
archive_generation() {
    # $1: complete package or installed release; $2: release id.
    valid_release "$2" && safe_path "$1" && safe_path "$BACKUP/generations/$2" || return 1
    if [ -e "$BACKUP/generations/$2" ] || [ -L "$BACKUP/generations/$2" ]; then
        valid_generation "$BACKUP/generations/$2" "$2"
        return $?
    fi
    identity "$1/SHA256SUMS" "${2#.c100x-}" && known_main_hook "$1/hooks/main.inc" \
        && identity "$1/hooks/menu.inc" "$MENU_HOOK_SHA" && safe_path "$TRANSFORM" \
        && identity "$TRANSFORM" "$TRANSFORM_SHA" || return 1
    mkdir -p "$BACKUP/generations" || return 1
    archive_stage=$(mktemp -d "$BACKUP/generations/stage.XXXXXX") || return 1
    cp "$1/hooks/main.inc" "$1/hooks/menu.inc" "$1/SHA256SUMS" "$archive_stage/" \
        && cp "$TRANSFORM" "$archive_stage/transform.awk" \
        && valid_generation "$archive_stage" "$2" && sync \
        && mv "$archive_stage" "$BACKUP/generations/$2" && sync
}
active_release() {
    awk '/^        source: "\.c100x-[0-9a-f]+\/C100XBridge.qml"$/ {
        sub(/^        source: "/, ""); sub(/\/C100XBridge.qml"$/, ""); print
    }' "$GUI/main.qml"
}
verify_current() {
    regular "$GUI/main.qml" && regular "$GUI/MainPage.qml" || return 1
    ACTIVE_RELEASE=
    if ! identity "$GUI/main.qml" "$MAIN_SHA"; then
        ACTIVE_RELEASE=$(active_release)
        valid_release "$ACTIVE_RELEASE" || return 1
        if [ ! -e "$BACKUP/generations/$ACTIVE_RELEASE" ] && [ "$ACTION" != status ]; then
            # Migration from the initial disk prototype. Never use arbitrary
            # installed hooks: all three recipe files must match fixed hashes.
            archive_generation "$GUI/$ACTIVE_RELEASE" "$ACTIVE_RELEASE" || return 1
        fi
        render_generation "$BACKUP/generations/$ACTIVE_RELEASE" "$ACTIVE_RELEASE" "$WORK/check" \
            && cmp -s "$GUI/main.qml" "$WORK/check/main.qml" || return 1
        cmp -s "$GUI/MainPage.qml" "$WORK/check/MainPage.qml" || identity "$GUI/MainPage.qml" "$MENU_SHA"
        return $?
    fi
    if identity "$GUI/MainPage.qml" "$MENU_SHA"; then return 0; fi
    # A power loss before the main switch can leave an inert menu hook only.
    for generation in "$BACKUP/generations"/.c100x-*; do
        [ -d "$generation" ] || continue
        if render_generation "$generation" "${generation##*/}" "$WORK/check" \
            && cmp -s "$GUI/MainPage.qml" "$WORK/check/MainPage.qml"; then return 0; fi
    done
    return 1
}
