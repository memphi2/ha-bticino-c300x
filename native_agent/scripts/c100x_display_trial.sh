# Persistent activation snapshots, authenticated by the archived stock recipe.
PENDING="$BACKUP/pending"
trial_exists() { [ -e "$PENDING" ] || [ -L "$PENDING" ]; }
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
    trial_stage=$(mktemp -d "$BACKUP/trial-stage.XXXXXX") || return 1
    cp -p "$WORK/before/main.qml" "$WORK/before/MainPage.qml" "$trial_stage/" || return 1
    printf '%s\n' "$RELEASE" > "$trial_stage/release"
    (GUI=$trial_stage; verify_current) || return 1
    sync && mv "$trial_stage" "$PENDING" && sync
}
archive_trial() {
    trial_history=$(mktemp -d "$BACKUP/trial-history.XXXXXX") || return 1
    mv "$PENDING" "$trial_history/snapshot" && sync
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
