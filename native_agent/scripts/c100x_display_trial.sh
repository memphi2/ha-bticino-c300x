# Persistent activation snapshots, authenticated by the archived stock recipe.
PENDING="$BACKUP/pending"
BOOT_ID=${C100X_BOOT_ID_FILE:-/proc/sys/kernel/random/boot_id}
trial_exists() { [ -e "$PENDING" ] || [ -L "$PENDING" ]; }
# Boot markers live next to pending, never inside it: the journal stays three files.
valid_boot_id() {
    case "$1" in ????????-????-????-????-????????????) ;; *) return 1 ;; esac
    case "$1" in *[!0-9a-f-]*) return 1 ;; esac
}
current_boot() {
    CURRENT_BOOT=
    read -r CURRENT_BOOT 2>/dev/null < "$BOOT_ID" || return 1
    valid_boot_id "$CURRENT_BOOT"
}
read_marker() {
    MARKER=
    regular "$BACKUP/$1" && [ "$(stat -c %s "$BACKUP/$1")" -le 128 ] || return 1
    read -r MARKER < "$BACKUP/$1"
}
write_marker() {
    marker_stage=$(mktemp "$BACKUP/boot-stage.XXXXXX") || return 1
    printf '%s\n' "$2" > "$marker_stage" && sync && mv -f "$marker_stage" "$BACKUP/$1" && sync
}
# none: no trial. prepare: the boot that prepared it. first: the first later
# boot, before init marked it. trial: that boot. later: a further boot with the
# trial still unconfirmed, or an invalid trial mark. stale: no valid prepare
# mark or no boot id.
boot_phase() {
    TRIAL_PHASE=none
    trial_exists || return 0
    TRIAL_PHASE=stale
    current_boot && read_marker pending.prepare-boot && valid_boot_id "$MARKER" || return 0
    if [ "$MARKER" = "$CURRENT_BOOT" ]; then TRIAL_PHASE=prepare; return 0; fi
    if [ ! -e "$BACKUP/pending.trial-boot" ] && [ ! -L "$BACKUP/pending.trial-boot" ]; then
        TRIAL_PHASE=first
        return 0
    fi
    TRIAL_PHASE=later
    if read_marker pending.trial-boot && [ "$MARKER" = "$CURRENT_BOOT" ]; then TRIAL_PHASE=trial; fi
}
note_result() {
    write_marker last-result "$1 $2" || printf '%s\n' 'c100x_display: result not recorded' >&2
}
verify_trial() {
    safe_path "$PENDING" && [ -d "$PENDING" ] && regular "$PENDING/release" || return 1
    TRIAL_RELEASE=$(cat "$PENDING/release")
    valid_release "$TRIAL_RELEASE" && valid_generation "$BACKUP/generations/$TRIAL_RELEASE" "$TRIAL_RELEASE" || return 1
    [ "$(find "$PENDING" -mindepth 1 | wc -l)" = 3 ] || return 1
    (GUI=$PENDING; verify_current) || return 1
    render_generation "$BACKUP/generations/$TRIAL_RELEASE" "$TRIAL_RELEASE" "$WORK/trial" || return 1
    # Never roll a later independent installation back using an old journal.
    for trial_file in main.qml MainPage.qml; do
        regular "$GUI/$trial_file" || return 1
        cmp -s "$GUI/$trial_file" "$PENDING/$trial_file" \
            || cmp -s "$GUI/$trial_file" "$WORK/trial/$trial_file" || return 1
    done
}
prepare_trial() {
    trial_exists && return 1
    # A stale trial mark would make the prepare boot count as a later boot.
    current_boot && rm -f "$BACKUP/pending.trial-boot" \
        && write_marker pending.prepare-boot "$CURRENT_BOOT" || return 1
    trial_stage=$(mktemp -d "$BACKUP/trial-stage.XXXXXX") || return 1
    cp -p "$WORK/before/main.qml" "$WORK/before/MainPage.qml" "$trial_stage/" || return 1
    printf '%s\n' "$RELEASE" > "$trial_stage/release"
    (GUI=$trial_stage; verify_current) || return 1
    sync && mv "$trial_stage" "$PENDING" && sync
}
archive_trial() {
    trial_history=$(mktemp -d "$BACKUP/trial-history.XXXXXX") || return 1
    mv "$PENDING" "$trial_history/snapshot" && sync \
        && rm -f "$BACKUP/pending.prepare-boot" "$BACKUP/pending.trial-boot"
}
rollback_trial() {
    verify_trial || return 1
    # Restore exactly the authenticated pre-trial state, including its modes.
    replace "$PENDING/main.qml" "$GUI/main.qml" \
        && replace "$PENDING/MainPage.qml" "$GUI/MainPage.qml" || return 1
    cmp -s "$PENDING/main.qml" "$GUI/main.qml" && cmp -s "$PENDING/MainPage.qml" "$GUI/MainPage.qml" || return 1
    # Once the authenticated prior state is back, a later archive/remount error
    # must never let cleanup reinstate the failed candidate.
    DIRTY=0
    archive_trial
}
confirm_trial() {
    verify_trial && verify_tree "$GUI/$TRIAL_RELEASE" || return 1
    cmp -s "$GUI/main.qml" "$WORK/trial/main.qml" \
        && cmp -s "$GUI/MainPage.qml" "$WORK/trial/MainPage.qml" || return 1
    identity "$GUI/$TRIAL_RELEASE/SHA256SUMS" "${TRIAL_RELEASE#.c100x-}" || return 1
    remount_ro || return 1
    probe_script=${C100X_PROBE_SCRIPT:-$AGENT/c100x_display_probe.sh}
    safe_path "$probe_script" && regular "$probe_script" || return 1
    . "$probe_script"
    probe_runtime "${TRIAL_RELEASE#.c100x-}" || return 1
    # Recheck disk identity after the GUI round trip and before committing.
    verify_trial && cmp -s "$GUI/main.qml" "$WORK/trial/main.qml" \
        && cmp -s "$GUI/MainPage.qml" "$WORK/trial/MainPage.qml" \
        && verify_tree "$GUI/$TRIAL_RELEASE" || return 1
}
