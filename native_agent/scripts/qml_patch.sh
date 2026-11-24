#!/bin/sh
set -eu

ACTION="${1:-status}"
GUI_DIR="${C300X_QML_GUI_DIR:-/home/bticino/bin/gui/skins/default}"
SOURCE_DIR="${C300X_QML_SOURCE_DIR:-${C300X_AGENT_DIR:-/home/bticino/cfg/extra/c300x-native-agent}/qml}"
BACKUP_DIR="${C300X_QML_BACKUP_DIR:-${C300X_BACKUP_ROOT:-/home/bticino/cfg/extra/c300x-device-file-backups}/original/gui/skins/default}"
NO_REMOUNT="${C300X_QML_NO_REMOUNT:-0}"
RELOAD_GUI="${C300X_QML_RELOAD_GUI:-1}"
GUI_ROOT="${C300X_QML_GUI_ROOT:-/home/bticino}"
GUI_WRAPPER="${C300X_QML_GUI_WRAPPER:-/home/bticino/bin/BtClass_qws}"
GUI_RELOAD_DELAY_SECONDS="${C300X_QML_GUI_RELOAD_DELAY_SECONDS:-2}"
PROC_DIR="${C300X_QML_PROC_DIR:-/proc}"
AGENT_BIN="${C300X_QML_AGENT_BIN:-${C300X_AGENT_DIR:-/home/bticino/cfg/extra/c300x-native-agent}/c300x-agent-native}"
# 1: stock layout, 0: side by side, unset: keep the layout on the device.
HOME_BUTTONS_REQUEST="${C300X_QML_DYNAMIC_HOME_PAGE:-}"
STAGING_DIR="${C300X_QML_STAGING_DIR:-${TMPDIR:-/tmp}/c300x-qml-patch.$$}"
CORE_PATCH_FILES="C300XRingerControl.qml js/c300x_ringer.js EventManager.qml"
MEDIA_USER_LABEL_FILES="Components/Settings/CallBlockPopup.qml"
# The display files this integration adds; every list of them derives from here.
GENERATED_FEATURE_FILES="C300XSettings.qml js/c300x_maintenance.js Alarm.qml HomeAssistant.qml C300XEnergy.qml C300XEnergyConsumers.qml js/c300x_energy_consumers.js C300XPageNavigation.qml C300XAgenda.qml C300XLeaveHome.qml C300XChecks.qml C300XSituations.qml C300XOptionalPages.qml C300XDetailControl.qml C300XEnergyReadout.qml C300XEnergySums.qml C300XAlerts.qml js/c300x_alerts.js js/c300x_energy.js js/c300x_ha.js js/c300x_i18n.js js/c300x_memos.js"
FEATURE_PATCH_FILES="Settings.qml MainApp.qml HomePage.qml MemoPage.qml Components/Settings/GeneralsChoice.qml $GENERATED_FEATURE_FILES"
PATCH_FILES="$FEATURE_PATCH_FILES $CORE_PATCH_FILES"
OBSOLETE_GUI_FILES="C300XText.qml C300XEnergyDistribution.qml images/c300x_alarm_icon.svg images/c300x_alarm_icon_p.svg images/c300x_home_assistant_icon.svg images/c300x_home_assistant_icon_p.svg"
TRANSACTION_STATE=
TRANSACTION_FORMAT=.c300x-v2
ROOT_RW_MARK="${TMPDIR:-/tmp}/c300x-qml-root-rw"

json_status() {
    changed_files="${1:-}"
    state=original
    patched=false
    core_state=original
    core_patched=false
    media_user_label_state=original
    media_user_label_patched=false
    backup_available=false
    core_backup_available=false
    media_user_label_backup_available=false
    gui_running=false
    if full_patch_present; then
        state=patched
        patched=true
    elif partial_patch_present; then
        state=partial
        patched=null
    fi
    if core_patch_present; then
        core_state=patched
        core_patched=true
    elif core_partial_patch_present; then
        core_state=partial
        core_patched=null
    fi
    if media_user_label_present; then
        media_user_label_state=patched
        media_user_label_patched=true
    elif media_user_label_partial_present; then
        media_user_label_state=partial
        media_user_label_patched=null
    fi
    if feature_backup_available; then
        backup_available=true
    fi
    if [ -f "$BACKUP_DIR/EventManager.qml" ]; then
        core_backup_available=true
    fi
    if [ -f "$BACKUP_DIR/Components/Settings/CallBlockPopup.qml" ]; then
        media_user_label_backup_available=true
    fi
    if command -v pidof >/dev/null 2>&1 && pidof BtClass >/dev/null 2>&1; then
        gui_running=true
    fi
    home_buttons="$(installed_home_buttons)"
    transaction_field=
    if [ -n "$TRANSACTION_STATE" ]; then
        transaction_field=",\"transaction\":\"$TRANSACTION_STATE\""
    fi
    if [ -n "$changed_files" ]; then
        printf '{"ok":true,"available":true,"state":"%s","patched":%s,"core_state":"%s","core_patched":%s,"media_user_label_state":"%s","media_user_label_patched":%s,"backup_available":%s,"core_backup_available":%s,"media_user_label_backup_available":%s,"gui_running":%s,"home_buttons":%s,"changed_files":%s%s}\n' "$state" "$patched" "$core_state" "$core_patched" "$media_user_label_state" "$media_user_label_patched" "$backup_available" "$core_backup_available" "$media_user_label_backup_available" "$gui_running" "$home_buttons" "$changed_files" "$transaction_field"
    else
        printf '{"ok":true,"available":true,"state":"%s","patched":%s,"core_state":"%s","core_patched":%s,"media_user_label_state":"%s","media_user_label_patched":%s,"backup_available":%s,"core_backup_available":%s,"media_user_label_backup_available":%s,"gui_running":%s,"home_buttons":%s%s}\n' "$state" "$patched" "$core_state" "$core_patched" "$media_user_label_state" "$media_user_label_patched" "$backup_available" "$core_backup_available" "$media_user_label_backup_available" "$gui_running" "$home_buttons" "$transaction_field"
    fi
}

installed_home_buttons() {
    if file_contains "$GUI_DIR/HomePage.qml" 'id: displayBridgeButtonRow'; then
        printf '"side_by_side"\n'
    elif file_contains "$GUI_DIR/HomePage.qml" '+ (page.alarmButtonVisible ? 1 : 0) + (page.haButtonVisible ? 1 : 0) + 2'; then
        printf '"stock"\n'
    else
        printf 'null\n'
    fi
}

json_reload_failed() {
    backup_available=false
    core_backup_available=false
    gui_running=false
    if feature_backup_available; then
        backup_available=true
    fi
    if [ -f "$BACKUP_DIR/EventManager.qml" ]; then
        core_backup_available=true
    fi
    if command -v pidof >/dev/null 2>&1 && pidof BtClass >/dev/null 2>&1; then
        gui_running=true
    fi
    transaction_field=
    if [ -n "$TRANSACTION_STATE" ]; then
        transaction_field=",\"transaction\":\"$TRANSACTION_STATE\""
    fi
    printf '{"ok":false,"available":true,"state":"reload_failed","patched":null,"core_state":"unknown","core_patched":null,"backup_available":%s,"core_backup_available":%s,"gui_running":%s%s}\n' "$backup_available" "$core_backup_available" "$gui_running" "$transaction_field"
}

file_contains() {
    file="$1"
    text="$2"
    [ -f "$file" ] && grep -F -q "$text" "$file"
}

feature_backup_available() {
    [ -f "$BACKUP_DIR/MainApp.qml" ] || return 1
    if file_contains "$GUI_DIR/Settings.qml" c300xSettings; then
        [ -f "$BACKUP_DIR/Settings.qml" ] && check_settings_paths 2>/dev/null || return 1
    fi
}

full_patch_present() {
    file_contains "$GUI_DIR/MainApp.qml" 'sourceUrl: "Alarm.qml"' \
        && file_contains "$GUI_DIR/MainApp.qml" 'sourceUrl: "HomeAssistant.qml"' \
        && file_contains "$GUI_DIR/MainApp.qml" 'alarmPage,' \
        && file_contains "$GUI_DIR/MainApp.qml" 'haPage,' \
        && file_contains "$GUI_DIR/MainApp.qml" 'id: c300xDisplayPreferences' \
        && file_contains "$GUI_DIR/MainApp.qml" 'property string bridgeProblem' \
        && file_contains "$GUI_DIR/Settings.qml" 'c300xIntegrationButton.checked = true' \
        && feature_port="$(station_ui_port)" \
        && file_contains "$GUI_DIR/MainApp.qml" "property string uiBaseUrl: \"http://127.0.0.1:$feature_port\"" \
        && file_contains "$GUI_DIR/MainApp.qml" 'id: c300xAlerts' \
        && file_contains "$GUI_DIR/EventManager.qml" 'function c300xPreemptAlert()' \
        && file_contains "$GUI_DIR/Settings.qml" 'sourceUrl: "C300XSettings.qml"' \
        && file_contains "$GUI_DIR/Settings.qml" 'c300xSettings.item.clearConfirmation()' \
        && file_contains "$GUI_DIR/Components/Settings/GeneralsChoice.qml" 'onTouched: global.beepEnabled = checked' \
        && [ -f "$GUI_DIR/C300XSettings.qml" ] && [ -f "$GUI_DIR/js/c300x_maintenance.js" ] \
        && ! general_settings_partial_present \
        && home_page_feature_patch_present \
        && file_contains "$GUI_DIR/HomePage.qml" 'MemoSync.syncHomeNotifications(page)' \
        && file_contains "$GUI_DIR/HomePage.qml" 'property alias memoEventRetryTimer: memoRetryTimer' \
        && file_contains "$GUI_DIR/HomePage.qml" 'objectName: "alarmButton"' \
        && file_contains "$GUI_DIR/HomePage.qml" 'objectName: "haButton"' \
        && file_contains "$GUI_DIR/HomePage.qml" 'images/call/icon_call-home.svg' \
        && file_contains "$GUI_DIR/MemoPage.qml" 'MemoSync.syncMemoModel' \
        && file_contains "$GUI_DIR/Alarm.qml" 'headerLabel: uiText("alarm")' \
        && file_contains "$GUI_DIR/HomeAssistant.qml" 'Api.dashboard' \
        && [ -f "$GUI_DIR/C300XEnergy.qml" ] \
        && [ -f "$GUI_DIR/C300XEnergyConsumers.qml" ] \
        && [ -f "$GUI_DIR/js/c300x_energy_consumers.js" ] \
        && [ -f "$GUI_DIR/C300XPageNavigation.qml" ] \
        && [ -f "$GUI_DIR/C300XAlerts.qml" ] \
        && [ -f "$GUI_DIR/js/c300x_alerts.js" ] \
        && [ -f "$GUI_DIR/C300XAgenda.qml" ] \
        && [ -f "$GUI_DIR/C300XLeaveHome.qml" ] \
        && [ -f "$GUI_DIR/C300XChecks.qml" ] \
        && [ -f "$GUI_DIR/C300XSituations.qml" ] \
        && [ -f "$GUI_DIR/C300XOptionalPages.qml" ] \
        && [ -f "$GUI_DIR/C300XDetailControl.qml" ] \
        && [ -f "$GUI_DIR/C300XEnergyReadout.qml" ] \
        && [ -f "$GUI_DIR/C300XEnergySums.qml" ] \
        && [ -f "$GUI_DIR/js/c300x_energy.js" ] \
        && file_contains "$GUI_DIR/js/c300x_ha.js" 'function homeButtons' \
        && file_contains "$GUI_DIR/js/c300x_ha.js" 'function loadDisplayPreferences' \
        && file_contains "$GUI_DIR/js/c300x_i18n.js" 'function weather' \
        && file_contains "$GUI_DIR/js/c300x_memos.js" 'function syncHomeNotifications' \
        && file_contains "$GUI_DIR/js/c300x_memos.js" 'function syncMemoModel'
}

partial_patch_present() {
    file_contains "$GUI_DIR/MainApp.qml" 'sourceUrl: "Alarm.qml"' \
        || file_contains "$GUI_DIR/MainApp.qml" 'id: c300xDisplayPreferences' \
        || file_contains "$GUI_DIR/MainApp.qml" 'sourceUrl: "HomeAssistant.qml"' \
        || file_contains "$GUI_DIR/HomePage.qml" 'id: homeAssistantButtonRow' \
        || file_contains "$GUI_DIR/HomePage.qml" 'function displayBridgeButtonCount()' \
        || file_contains "$GUI_DIR/HomePage.qml" 'id: displayBridgeButtonRow' \
        || file_contains "$GUI_DIR/HomePage.qml" 'property bool alarmButtonVisible' \
        || file_contains "$GUI_DIR/MemoPage.qml" 'MemoSync.syncMemoModel' \
        || file_contains "$GUI_DIR/Settings.qml" c300xSettings \
        || general_settings_partial_present \
        || generated_feature_file_present
}

generated_feature_file_present() {
    for present_rel in $GENERATED_FEATURE_FILES; do
        if [ -f "$GUI_DIR/$present_rel" ]; then
            return 0
        fi
    done
    return 1
}

general_settings_partial_present() {
    file_contains "$GUI_DIR/Components/Settings/GeneralsChoice.qml" 'c300xDisplayPreferences' \
        || file_contains "$GUI_DIR/Components/Settings/GeneralsChoice.qml" 'c300xFeedbackSetting'
}

home_page_feature_patch_present() {
    file_contains "$GUI_DIR/HomePage.qml" 'page.startMessageNotificationWatch()' || return 1
    file_contains "$GUI_DIR/HomePage.qml" 'id: buttonRetryTimer' || return 1
    file_contains "$GUI_DIR/HomePage.qml" 'if (registrationPossible) page.buttonRetries = 0' || return 1
    file_contains "$GUI_DIR/HomePage.qml" 'id: c300xBridgeHint' || return 1
    file_contains "$GUI_DIR/HomePage.qml" 'id: displayBridgeButtonRow' \
        || (
            file_contains "$GUI_DIR/HomePage.qml" 'HAConfig.homeButtons' \
            && file_contains "$GUI_DIR/HomePage.qml" '+ (page.alarmButtonVisible ? 1 : 0) + (page.haButtonVisible ? 1 : 0) + 2'
        )
}

core_patch_present() {
    file_contains "$GUI_DIR/EventManager.qml" 'function c300xNotifyMediaClosed()' \
        && core_port="$(station_ui_port)" \
        && file_contains "$GUI_DIR/EventManager.qml" "C300XRingerControl { id: c300xRinger; uiBaseUrl: \"http://127.0.0.1:$core_port\" }" \
        && file_contains "$GUI_DIR/EventManager.qml" 'request.open("GET", c300xRinger.uiBaseUrl + "/ui/media-closed", true)' \
        && file_contains "$GUI_DIR/EventManager.qml" 'function c300xPreemptAlert()' \
        && cmp -s "$SOURCE_DIR/C300XRingerControl.qml" "$GUI_DIR/C300XRingerControl.qml" \
        && cmp -s "$SOURCE_DIR/js/c300x_ringer.js" "$GUI_DIR/js/c300x_ringer.js" \
        && core_call_end_hooks_present
}

core_partial_patch_present() {
    file_contains "$GUI_DIR/EventManager.qml" 'function c300xNotifyMediaClosed()' \
        || file_contains "$GUI_DIR/EventManager.qml" '/ui/media-closed' \
        || file_contains "$GUI_DIR/EventManager.qml" 'c300xNotifyMediaClosed()' \
        || file_contains "$GUI_DIR/EventManager.qml" 'C300XRingerControl {' \
        || [ -f "$GUI_DIR/C300XRingerControl.qml" ] \
        || [ -f "$GUI_DIR/js/c300x_ringer.js" ]
}

media_user_label_present() {
    file_contains "$GUI_DIR/Components/Settings/CallBlockPopup.qml" 'Forward calls to Home Assistant' \
        && file_contains "$GUI_DIR/Components/Settings/CallBlockPopup.qml" 'Calls forwarded to Home Assistant'
}

media_user_label_partial_present() {
    file_contains "$GUI_DIR/Components/Settings/CallBlockPopup.qml" 'Forward calls to Home Assistant' \
        || file_contains "$GUI_DIR/Components/Settings/CallBlockPopup.qml" 'Calls forwarded to Home Assistant'
}

core_call_end_hooks_present() {
    [ -f "$GUI_DIR/EventManager.qml" ] || return 1
    awk '
        $0 == "        onCallEnded: {" {
            count += 1
            if ((getline next_line) <= 0 || next_line != "            c300xPreemptAlert()") {
                bad = 1
            }
            if ((getline next_line) <= 0 || next_line != "            c300xNotifyMediaClosed()") {
                bad = 1
            }
        }
        END {
            if (bad) {
                exit 2
            }
            if (count < 1) {
                exit 1
            }
        }
    ' "$GUI_DIR/EventManager.qml"
}

# The swipe threshold of the display library belongs to the Display patch and
# follows it. The agent binary checks, backs up and replaces the file. What
# happens next follows the state found, not what this run did, so a run that
# was cut off is completed by the next one: a display that still runs the
# replaced file is restarted, and a root file system left writable goes
# read-only again. A display that does not start with the changed library
# gets the stock one back.
touch_display_stale() {
    for touch_pid in $(pidof BtClass 2>/dev/null || true); do
        if grep -q '/usr/lib/.*(deleted)' "$PROC_DIR/$touch_pid/maps" 2>/dev/null; then
            return 0
        fi
    done
    return 1
}

touch_root_read_only() {
    if [ "$NO_REMOUNT" = "1" ] || ! grep -q '^[^ ]* / [^ ]* rw[, ]' "$PROC_DIR/mounts" 2>/dev/null; then
        return 0
    fi
    for touch_try in 1 2 3 4 5; do
        if remount_ro; then
            return 0
        fi
        sleep 1
    done
    return 1
}

touch_patch() {
    TOUCH_STATE=
    if [ ! -x "$AGENT_BIN" ] || [ "${GUI_RELOAD_FAILED:-0}" = "1" ]; then
        return 0
    fi
    touch_result="$("$AGENT_BIN" --display-touch "$1" 2>/dev/null || true)"
    touch_changed=0
    case "$touch_result" in
        *'"changed":true'*) touch_changed=1 ;;
    esac
    # A restore that does not answer "ok" has failed, a crash included.
    case "$1:$touch_result" in
        restore:*'"ok":true'*) ;;
        restore:*) TOUCH_STATE=restore_failed ;;
    esac
    if [ "$touch_changed" = "1" ] || { [ "$RELOAD_GUI" = "1" ] && touch_display_stale; }; then
        if ! reload_gui; then
            if [ "$1" = "apply" ]; then
                touch_result="$("$AGENT_BIN" --display-touch restore 2>/dev/null || true)"
                if ! reload_gui; then
                    GUI_RELOAD_FAILED=1
                else
                    case "$touch_result" in
                        *'"ok":true'*) TOUCH_STATE=rolled_back ;;
                        *) TOUCH_STATE=restore_failed ;;
                    esac
                fi
            else
                GUI_RELOAD_FAILED=1
            fi
        fi
    fi
    if ! touch_root_read_only; then
        TOUCH_ROOT_WRITABLE=1
    fi
}

abort_touch_phase() {
    trap - HUP INT TERM
    if [ "$RELOAD_GUI" = "1" ] && { touch_display_stale || ! pidof BtClass >/dev/null 2>&1; }; then
        reload_gui || true
    fi
    touch_root_read_only || true
    exit 131
}

run_touch_phase() {
    trap abort_touch_phase HUP INT TERM
    touch_patch "$1"
}

reload_gui() {
    if [ "$RELOAD_GUI" != "1" ]; then
        return 0
    fi
    if command -v killall >/dev/null 2>&1; then
        killall BtClass >/dev/null 2>&1 || true
    fi
    sleep "$GUI_RELOAD_DELAY_SECONDS"
    if command -v pidof >/dev/null 2>&1 && pidof BtClass >/dev/null 2>&1; then
        return 0
    fi
    if [ -f "$GUI_WRAPPER" ]; then
        # A session of its own: the agent kills this script's process group
        # when a job passes its time limit, and the GUI must outlive that.
        gui_session=
        if command -v setsid >/dev/null 2>&1; then
            gui_session=setsid
        fi
        (
            cd "$GUI_ROOT"
            $gui_session /bin/sh "$GUI_WRAPPER" >/tmp/BtClass_qws.agent.log 2>&1 &
        )
    fi
    sleep "$GUI_RELOAD_DELAY_SECONDS"
    if ! command -v pidof >/dev/null 2>&1; then
        return 1
    fi
    # Process presence only: the firmware exposes no QML readiness handshake here.
    pidof BtClass >/dev/null 2>&1
}

remount_rw() {
    if [ "$NO_REMOUNT" = "1" ]; then
        return 0
    fi
    printf '%s %s\n' "$$" "$GUI_DIR" > "$ROOT_RW_MARK" 2>/dev/null || true
    mount -o remount,rw / >/dev/null 2>&1
}

remount_ro() {
    if [ "$NO_REMOUNT" = "1" ]; then
        return 0
    fi
    mount -o remount,ro / >/dev/null 2>&1 || return 1
    rm -f "$ROOT_RW_MARK"
}

root_left_writable() {
    [ "$NO_REMOUNT" != "1" ] && [ -f "$ROOT_RW_MARK" ] || return 1
    read -r mark_pid mark_gui < "$ROOT_RW_MARK" || return 1
    [ "$mark_gui" = "$GUI_DIR" ] && ! transaction_owner_running "$mark_pid"
}

rollback_transaction() {
    [ -f "$1/.c300x-files" ] || return 1
    rollback_ok=1
    while read -r rollback_entry; do
        rollback_rel="${rollback_entry#?}"
        rollback_target="$GUI_DIR/$rollback_rel"
        case "$rollback_entry" in
            -*)
                if [ -e "$rollback_target" ] || [ -L "$rollback_target" ]; then
                    if ! : > "$1/.c300x-reload" || ! rm -f "$rollback_target"; then
                        rollback_ok=0
                    fi
                fi
                ;;
            *)
                if [ -f "$1/$rollback_rel" ]; then
                    if ! cmp -s "$1/$rollback_rel" "$rollback_target" && ! : > "$1/.c300x-reload"; then
                        rollback_ok=0
                    elif ! mkdir -p "$(dirname "$rollback_target")" \
                        || ! mv -f "$1/$rollback_rel" "$rollback_target"; then
                        rollback_ok=0
                    fi
                fi
                ;;
        esac
    done < "$1/.c300x-files"
    [ "$rollback_ok" = "1" ]
}

remove_transaction() {
    rm -f "$1/.c300x-reload" "$1/.c300x-files" "$1/.c300x-files.tmp" || return 1
    for remove_entry in "$1"/*; do
        rm -rf "$remove_entry" || return 1
    done
    rm -f "$1/.c300x-stuck" || return 1
    rm -f "$1/$TRANSACTION_FORMAT" && rm -rf "$1"
}

transaction_owner_running() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
    esac
    kill -0 "$1" 2>/dev/null || return 1
    [ -r "$PROC_DIR/$1/cmdline" ] || return 0
    tr '\000' ' ' < "$PROC_DIR/$1/cmdline" | grep -q -F "${0##*/}"
}

leftover_transaction() {
    leftover_pid="${1##*.}"
    case "$leftover_pid" in
        ''|*[!0-9]*) return 1 ;;
    esac
    if [ ! -d "$1" ] || [ -L "$1" ] || [ "$leftover_pid" = "$$" ]; then
        return 1
    fi
    if transaction_owner_running "$leftover_pid"; then
        TRANSACTION_LIVE=1
        return 1
    fi
}

legacy_copy_verified() {
    find "$1" | while read -r legacy_path; do
        if [ -d "$legacy_path" ] && [ ! -L "$legacy_path" ]; then
            continue
        fi
        legacy_rel="${legacy_path#"$1"/}"
        [ "$legacy_rel" != ".c300x-reload" ] || continue
        [ -f "$legacy_path" ] && [ ! -L "$legacy_path" ] || exit 1
        case " $OBSOLETE_GUI_FILES " in
            *" $legacy_rel "*) continue ;;
        esac
        case " $PATCH_FILES $MEDIA_USER_LABEL_FILES " in
            *" $legacy_rel "*) ;;
            *) exit 1 ;;
        esac
        cmp -s "$legacy_path" "$GUI_DIR/$legacy_rel" && continue
        if [ -f "$BACKUP_DIR/$legacy_rel" ] && cmp -s "$legacy_path" "$BACKUP_DIR/$legacy_rel"; then
            continue
        fi
        if is_generated_patch_file "$legacy_rel" && cmp -s "$legacy_path" "$SOURCE_DIR/$legacy_rel"; then
            continue
        fi
        exit 1
    done
}

legacy_copy_superseded() {
    [ ! -e "$1/.c300x-reload" ] || return 1
    for legacy_rel in $PATCH_FILES $MEDIA_USER_LABEL_FILES; do
        [ ! "$GUI_DIR/$legacy_rel" -nt "$1" ] || return 0
    done
    return 1
}

restore_legacy_transaction() {
    [ ! -e "$1/.c300x-stuck" ] && legacy_copy_verified "$1" || return 1
    ! legacy_copy_superseded "$1" || return 0
    for legacy_rel in $PATCH_FILES $MEDIA_USER_LABEL_FILES; do
        if [ ! -f "$1/$legacy_rel" ] || cmp -s "$1/$legacy_rel" "$GUI_DIR/$legacy_rel"; then
            continue
        fi
        if ! : > "$1/.c300x-reload" \
            || ! mkdir -p "$(dirname "$GUI_DIR/$legacy_rel")" \
            || ! mv -f "$1/$legacy_rel" "$GUI_DIR/$legacy_rel"; then
            return 1
        fi
    done
}

settle_transaction() {
    if [ ! -f "$1/$TRANSACTION_FORMAT" ]; then
        restore_legacy_transaction "$1"
    elif [ -f "$1/.c300x-files" ]; then
        rollback_transaction "$1"
    fi
}

transaction_report() {
    TRANSACTION_LIVE=0
    for report_dir in "$GUI_DIR"/.c300x-qml-transaction.*; do
        leftover_transaction "$report_dir" || continue
        if [ -e "$report_dir/.c300x-stuck" ]; then
            TRANSACTION_STATE=stuck
        elif [ "$TRANSACTION_STATE" != "stuck" ]; then
            TRANSACTION_STATE=pending
        fi
    done
}

recover_transactions() {
    transaction_report
    [ "$TRANSACTION_LIVE" = "0" ] || return 1
    recover_ro=0
    if root_left_writable; then
        recover_ro=1
    fi
    recover_stuck=
    recover_blocked=0
    recover_reload=0
    if [ -n "$TRANSACTION_STATE" ]; then
        TRANSACTION_STATE=
        recover_ro=1
        remount_rw || true
        for recover_dir in "$GUI_DIR"/.c300x-qml-transaction.*; do
            leftover_transaction "$recover_dir" || continue
            if settle_transaction "$recover_dir"; then
                rm -f "$recover_dir/.c300x-stuck"
                if [ -e "$recover_dir/.c300x-reload" ]; then
                    recover_reload=1
                fi
            else
                : > "$recover_dir/.c300x-stuck" 2>/dev/null || true
                recover_stuck="$recover_stuck ${recover_dir##*.} "
                if [ -f "$recover_dir/$TRANSACTION_FORMAT" ]; then
                    recover_blocked=1
                fi
            fi
        done
        if [ "$recover_reload" = "1" ]; then
            reload_gui || true
        fi
        for recover_dir in "$GUI_DIR"/.c300x-qml-transaction.*; do
            leftover_transaction "$recover_dir" || continue
            case "$recover_stuck" in
                *" ${recover_dir##*.} "*)
                    TRANSACTION_STATE=stuck
                    continue
                    ;;
            esac
            if ! remove_transaction "$recover_dir"; then
                TRANSACTION_STATE=stuck
                recover_blocked=1
            elif [ "$TRANSACTION_STATE" != "stuck" ]; then
                TRANSACTION_STATE=recovered
            fi
        done
    fi
    if [ "$recover_ro" = "1" ]; then
        remount_ro || true
    fi
    [ "$recover_blocked" = "0" ]
}

finish_signal() {
    FINISH_SIGNALLED=1
    FINISH_STEP_SIGNALLED=1
}

finish_step() {
    FINISH_STEP_SIGNALLED=0
    finish_step_rc=0
    "$@" || finish_step_rc=$?
    if [ "$FINISH_STEP_SIGNALLED" = "1" ]; then
        FINISH_STEP_SIGNALLED=0
        finish_step_rc=0
        "$@" || finish_step_rc=$?
    fi
    return "$finish_step_rc"
}

finish_write_action() {
    write_rc=$?
    trap - EXIT
    FINISH_SIGNALLED=0
    trap finish_signal HUP INT TERM
    if [ "$write_rc" != "0" ]; then
        cleanup_staging
    fi
    recovery_ok=1
    restart_previous=0
    if [ "${WRITE_TRANSACTION_READY:-0}" = "1" ] && [ "${WRITE_TRANSACTION_COMMITTED:-0}" != "1" ]; then
        restart_previous="${WRITE_RELOAD_ATTEMPTED:-0}"
        finish_step rollback_transaction "$WRITE_TRANSACTION" || recovery_ok=0
    fi
    if [ "$restart_previous" = "1" ] && [ "$recovery_ok" = "1" ]; then
        if ! finish_step reload_gui; then
            printf 'Previous GUI files restored, but GUI restart could not be confirmed\n' >&2
        fi
    fi
    if [ "$recovery_ok" = "1" ]; then
        if [ -n "${WRITE_TRANSACTION:-}" ]; then
            finish_step remove_transaction "$WRITE_TRANSACTION" || write_rc=1
        fi
    else
        printf 'GUI rollback failed; recovery files retained in %s\n' "$WRITE_TRANSACTION" >&2
        write_rc=1
    fi
    if [ "${WRITE_TRANSACTION_COMMITTED:-0}" = "1" ] && [ "${REMOVE_EMPTY_JS:-0}" = "1" ]; then
        rmdir "$GUI_DIR/js" >/dev/null 2>&1 || true
    fi
    write_root_ro=1
    if ! finish_step remount_ro; then
        write_rc=1
        write_root_ro=0
    fi
    trap - HUP INT TERM
    if [ "$FINISH_SIGNALLED" = "1" ]; then
        exit_write_signal
    fi
    return "$write_rc"
}

exit_write_signal() {
    if [ "$recovery_ok" = "1" ] && [ "$write_root_ro" = "1" ] && [ "${WRITE_TRANSACTION_COMMITTED:-0}" != "1" ]; then
        exit 130
    fi
    exit 131
}

abort_write_action() {
    finish_write_action || true
    exit_write_signal
}

run_write_action() {
    WRITE_TRANSACTION=
    WRITE_TRANSACTION_READY=0
    WRITE_TRANSACTION_COMMITTED=0
    WRITE_RELOAD_ATTEMPTED=0
    REMOVE_EMPTY_JS=0
    trap finish_write_action EXIT
    trap abort_write_action HUP INT TERM
    remount_rw
    # Keep recovery on the GUI filesystem so rollback needs no further copies.
    transaction_dir="$GUI_DIR/.c300x-qml-transaction.$$"
    (umask 077; mkdir "$transaction_dir")
    WRITE_TRANSACTION="$transaction_dir"
    : > "$WRITE_TRANSACTION/$TRANSACTION_FORMAT"
    sync
    for transaction_rel in $PATCH_FILES $MEDIA_USER_LABEL_FILES $OBSOLETE_GUI_FILES; do
        transaction_source="$GUI_DIR/$transaction_rel"
        if [ -L "$transaction_source" ] || { [ -e "$transaction_source" ] && [ ! -f "$transaction_source" ]; }; then
            printf 'Unsupported GUI file type: %s\n' "$transaction_source" >&2
            return 1
        fi
        transaction_mark=-
        if [ -f "$transaction_source" ]; then
            mkdir -p "$(dirname "$WRITE_TRANSACTION/$transaction_rel")"
            cp -p "$transaction_source" "$WRITE_TRANSACTION/$transaction_rel"
            transaction_mark=+
        fi
        printf '%s%s\n' "$transaction_mark" "$transaction_rel" >> "$WRITE_TRANSACTION/.c300x-files.tmp"
    done
    sync
    mv -f "$WRITE_TRANSACTION/.c300x-files.tmp" "$WRITE_TRANSACTION/.c300x-files"
    sync
    WRITE_TRANSACTION_READY=1
    "$@"
    WRITE_RELOAD_ATTEMPTED=1
    if ! reload_gui; then
        GUI_RELOAD_FAILED=1
        finish_write_action
        return
    fi
    WRITE_TRANSACTION_COMMITTED=1
    finish_write_action
}

json_write_status() {
    if [ "${GUI_RELOAD_FAILED:-0}" = "1" ]; then
        json_reload_failed
    else
        write_status="$(json_status "$changed_count")"
        if [ "${TOUCH_STATE:-}" = "restore_failed" ]; then
            write_status="$(printf '%s\n' "$write_status" \
                | sed 's/^{"ok":true/{"ok":false,"error":"display_library_restore_failed"/')"
        elif [ -n "${TOUCH_STATE:-}" ]; then
            write_status="$(printf '%s\n' "$write_status" \
                | sed "s/}\$/,\"display_library\":\"$TOUCH_STATE\"}/")"
        fi
        if [ "${TOUCH_ROOT_WRITABLE:-0}" = "1" ]; then
            write_status="$(printf '%s\n' "$write_status" | sed 's/}$/,"root_writable":true}/')"
        fi
        printf '%s\n' "$write_status"
    fi
}

stock_file_valid() {
    stock_file="$1"
    stock_rel="$2"
    if [ ! -f "$stock_file" ] || [ -L "$stock_file" ] || [ ! -s "$stock_file" ]; then
        printf 'Incomplete stock file: %s\n' "$stock_file" >&2
        return 1
    fi
    stock_file_unpatched "$stock_file" "$stock_rel" || return 1
    if ! grep -q '^import QtQuick' "$stock_file" \
        || ! awk 'NF { last = $0 } END { exit !(last ~ /^}[[:space:]]*$/) }' "$stock_file"; then
        printf 'Incomplete stock file: %s\n' "$stock_file" >&2
        return 1
    fi
}

stock_file_unpatched() {
    stock_file="$1"
    stock_rel="$2"
    case "$stock_rel" in
        HomePage.qml|MemoPage.qml)
            require_clean_original_page "$stock_file" "$stock_rel"
            ;;
        Components/Settings/CallBlockPopup.qml)
            require_clean_call_block_popup "$stock_file"
            ;;
        Components/Settings/GeneralsChoice.qml)
            require_clean_general_settings "$stock_file"
            ;;
        Settings.qml)
            ! file_contains "$stock_file" c300xSettings || { echo "Missing original Settings.qml backup" >&2; return 1; }
            render_settings "$stock_file" >/dev/null || return 1
            ;;
        EventManager.qml)
            if grep -F -q 'function c300xNotifyMediaClosed()' "$stock_file"; then
                printf 'Refusing to back up an already patched EventManager.qml\n' >&2
                return 1
            fi
            ;;
        MainApp.qml)
            if grep -F -q 'sourceUrl: "Alarm.qml"' "$stock_file" \
                || grep -F -q 'sourceUrl: "HomeAssistant.qml"' "$stock_file" \
                || grep -F -q 'c300xDisplayPreferences' "$stock_file"; then
                printf 'Refusing to back up an already patched MainApp.qml\n' >&2
                return 1
            fi
            ;;
    esac
}

stock_backup_valid() {
    stock_file_valid "$BACKUP_DIR/$1" "$1"
}

backup_file() {
    backup_rel="$1"
    backup_src="$GUI_DIR/$backup_rel"
    backup_dest="$BACKUP_DIR/$backup_rel"
    if [ -e "$backup_dest" ]; then
        stock_backup_valid "$backup_rel"
        return
    fi
    if [ ! -f "$backup_src" ]; then
        return 0
    fi
    stock_file_valid "$backup_src" "$backup_rel"
    mkdir -p "$(dirname "$backup_dest")"
    backup_temp_dir="$(mktemp -d "$backup_dest.tmp.XXXXXX")" || return 1
    if ! cp -p "$backup_src" "$backup_temp_dir/original" \
        || ! sync \
        || ! mv -f "$backup_temp_dir/original" "$backup_dest"; then
        rm -rf "$backup_temp_dir"
        return 1
    fi
    rmdir "$backup_temp_dir"
    sync
}

install_file() {
    install_rel="$1"
    backup_mode="${2:-original}"
    install_src="$SOURCE_DIR/$install_rel"
    install_dest="${PATCH_OUTPUT_DIR:-$GUI_DIR}/$install_rel"
    if [ ! -f "$install_src" ]; then
        printf 'Missing display source file: %s\n' "$install_rel" >&2
        return 1
    fi
    if [ "$backup_mode" = "original" ]; then
        backup_file "$install_rel"
    fi
    mkdir -p "$(dirname "$install_dest")"
    cp -p "$install_src" "$install_dest"
}

copy_generated_file() {
    # C300X_EMBEDDED_DISPLAY_FILES
    install_file "$1" generated
}

require_clean_original_page() {
    page_file="$1"
    page_name="$2"
    [ -s "$page_file" ]
    if grep -F -q 'homeAssistantButtonRow' "$page_file" \
        || grep -F -q 'homeAssistantButtonColumn' "$page_file" \
        || grep -F -q 'alarmButtonVisible' "$page_file" \
        || grep -F -q 'MemoSync.syncMemoModel' "$page_file"; then
        printf 'Refusing to patch %s from an already patched source\n' "$page_name" >&2
        return 1
    fi
}

require_clean_call_block_popup() {
    page_file="$1"
    [ -s "$page_file" ]
    if grep -F -q 'Forward calls to Home Assistant' "$page_file" \
        || grep -F -q 'Calls forwarded to Home Assistant' "$page_file"; then
        printf 'Refusing to patch CallBlockPopup.qml from an already patched source\n' >&2
        return 1
    fi
}

verify_generated_page() {
    page_file="$1"
    page_name="$2"
    shift 2
    [ -s "$page_file" ]
    for marker in "$@"; do
        if ! grep -F -q "$marker" "$page_file"; then
            printf 'Generated %s is missing marker: %s\n' "$page_name" "$marker" >&2
            return 1
        fi
    done
}

require_clean_general_settings() {
    [ -s "$1" ]
    if grep -E -q 'c300xDisplayPreferences|c300xFeedbackSetting' "$1"; then
        printf 'Refusing to back up or patch already patched GeneralsChoice.qml\n' >&2
        return 1
    fi
}

check_settings_paths() {
    for base in "$GUI_DIR" "$BACKUP_DIR"; do
        for rel in Settings.qml Components Components/Settings Components/Settings/GeneralsChoice.qml js C300XSettings.qml js/c300x_maintenance.js; do
            if [ -L "$base/$rel" ]; then
                printf 'Unsafe settings symlink: %s\n' "$base/$rel" >&2; return 1
            fi
        done
    done
    for rel in C300XSettings.qml js/c300x_maintenance.js; do
        if [ -e "$BACKUP_DIR/$rel" ]; then
            printf 'Unexpected original for generated settings file: %s\n' "$rel" >&2; return 1
        fi
    done
    for rel in Settings.qml Components/Settings/GeneralsChoice.qml; do
        original="$BACKUP_DIR/$rel"
        if [ -e "$original" ] && { [ ! -f "$original" ] || [ ! -s "$original" ]; }; then
            printf 'Invalid stock settings backup: %s\n' "$rel" >&2; return 1
        fi
    done
    if [ -f "$BACKUP_DIR/Components/Settings/GeneralsChoice.qml" ]; then
        require_clean_general_settings "$BACKUP_DIR/Components/Settings/GeneralsChoice.qml" || return 1
    fi
    if file_contains "$BACKUP_DIR/Settings.qml" c300xSettings; then
        printf 'Already patched Settings.qml backup\n' >&2; return 1
    fi
    if [ -f "$BACKUP_DIR/Settings.qml" ]; then
        render_settings "$BACKUP_DIR/Settings.qml" >/dev/null || return 1
    fi
}

patch_general_settings() {
    check_settings_paths
    settings_rel="Components/Settings/GeneralsChoice.qml"
    settings_original="$BACKUP_DIR/$settings_rel"
    settings_output="${PATCH_OUTPUT_DIR:-$GUI_DIR}/$settings_rel"
    backup_file "$settings_rel"
    if [ ! -f "$settings_original" ]; then
        printf 'Missing original GeneralsChoice.qml backup\n' >&2
        return 1
    fi
    require_clean_general_settings "$settings_original"
    mkdir -p "$(dirname "$settings_output")"
    cp -p "$settings_original" "$settings_output"
    verify_generated_page "$settings_output" "$settings_rel" \
        'checked: global.beepEnabled' 'onTouched: global.beepEnabled = checked'
    # Upgrades discard only the legacy feedback row by staging the preserved original.
    backup_file Settings.qml
    stock="$BACKUP_DIR/Settings.qml"
    if file_contains "$stock" c300xSettings; then return 1; fi
    cp -p "$stock" "$PATCH_OUTPUT_DIR/Settings.qml"
    render_settings "$stock" > "$PATCH_OUTPUT_DIR/Settings.qml"
}

render_settings() {
    awk '
        NF { last = $0 }
        $0 == "import QtQuick 1.1" { imports++ }
        $0 == "    function handleScreenOff() {" {
            print; print "        if (c300xSettings.item) c300xSettings.item.clearConfirmation()"; screen++; next
        }
        $0 == "    function aboutToShow() {" {
            print
            print "        if (typeof c300xDisplayPreferences !== \"undefined\" && c300xDisplayPreferences.openIntegration) {"
            print "            c300xDisplayPreferences.openIntegration = false"
            print "            c300xIntegrationButton.checked = true"
            print "        }"
            shows++; next
        }
        $0 == "                configurationChoice" {
            print $0 ","; print "                c300xSettings"; tabs++; next
        }
        $0 == "        spacing: 6" { print "        spacing: 4"; gaps++; next }
        $0 == "    ExclusiveGroup {" {
            print "    BasicButton {"
            print "        visible: typeof c300xDisplayPreferences !== \"undefined\""
            print "        anchors.right: column.right"
            print "        anchors.top: column.bottom"
            print "        anchors.topMargin: 4"
            print "        id: c300xIntegrationButton"
            print "        property Item tab: c300xSettings"
            print "        checkable: true"
            print "        exclusiveGroup: menuGroup"
            print "        style: CheckableButtonStyle {"
            print "            defaultImage: \"images/settings/settings-menu_btn.svg\""
            print "            checkedImage: \"images/settings/settings-menu_btn_p.svg\""
            print "            description: (trsl.language === \"it\" ? \"Integrazione\" : \"Integration\") + trsl.empty"
            print "        }"
            print "    }"
            print "    PageLoader {"
            print "        id: c300xSettings"
            print "        anchors.fill: sectionView"
            print "        sourceUrl: \"C300XSettings.qml\""
            print "    }"
            groups++
        }
        /append\(\{label: QT_TR_NOOP\("Configuration"\), tab: configurationChoice,/ { config++ }
        { print }
        END { if (imports != 1 || last != "}" || screen != 1 || shows != 1 || tabs != 1 || groups != 1 || gaps != 1 || config != 1) {
            print "Unsupported Settings.qml layout" > "/dev/stderr"; exit 12
        } }
    ' "$1"
}

home_buttons_layout() {
    case "$HOME_BUTTONS_REQUEST" in
        1) printf 'stock\n' ;;
        0) printf 'side_by_side\n' ;;
        *)
            if file_contains "$GUI_DIR/HomePage.qml" 'id: displayBridgeButtonRow' \
                || file_contains "$GUI_DIR/HomePage.qml" 'id: homeAssistantButtonRow'; then
                printf 'side_by_side\n'
            else
                printf 'stock\n'
            fi
            ;;
    esac
}

patch_home_page() {
    layout="$(home_buttons_layout)"
    output_dir="${PATCH_OUTPUT_DIR:-$GUI_DIR}"
    home_page="$output_dir/HomePage.qml"
    source_home_page="$BACKUP_DIR/HomePage.qml"
    temp_file="$output_dir/HomePage.qml.tmp.$$"
    backup_file "HomePage.qml"
    if [ ! -f "$source_home_page" ]; then
        printf 'Missing original HomePage.qml backup\n' >&2
        return 1
    fi
    mkdir -p "$output_dir"
    require_clean_original_page "$source_home_page" "HomePage.qml"
    awk -v layout="$layout" '
        function print_memo_sync_import() {
            if (!printed_memo_sync_import) {
                print "import \"js/c300x_memos.js\" as MemoSync"
                print "import \"js/c300x_ha.js\" as HAConfig"
                printed_memo_sync_import=1
            }
        }
        function print_home_notification_helpers() {
            print ""
            print "    property int externalUnreadMessages: -1"
            print "    property int externalUnreadMemos: -1"
            print "    property string uiBaseUrl: c300xDisplayPreferences.uiBaseUrl"
            print "    property alias memoEventRetryTimer: memoRetryTimer"
            print ""
            print "    Timer {"
            print "        id: memoRetryTimer"
            print "        repeat: false"
            print "        running: false"
            print "        onTriggered: MemoSync.retryEventWatch()"
            print "    }"
            print ""
            print "    function unreadMessagesCount() {"
            print "        return externalUnreadMessages >= 0 ? externalUnreadMessages : answeringModel.obj.unreadMessages"
            print "    }"
            print ""
            print "    function unreadMemosCount() {"
            print "        return externalUnreadMemos >= 0 ? externalUnreadMemos : answeringModel.obj.unreadMemos"
            print "    }"
            print ""
            print "    function refreshMessageNotifications() {"
            print "        MemoSync.syncHomeNotifications(page)"
            print "    }"
            print ""
            print "    function handleMessageNotificationEvent(event) {"
            print "        var registrationPossible = event && (event.missedRevisions || event.topic === \"display_bridge.state\")"
            print "        if (registrationPossible || (event && event.topic === \"notifications\")) {"
            print "            if (registrationPossible) page.buttonRetries = 0"
            print "            HAConfig.invalidateSharedRead(\"/ui/state\")"
            print "            refreshDisplayBridgeButtons()"
            print "        }"
            print "        if (event && (event.topic === \"memos\" || event.topic === \"answering_machine.messages\")) {"
            print "            refreshMessageNotifications()"
            print "        }"
            print "    }"
            print ""
            print "    function startMessageNotificationWatch() {"
            print "        stopMessageNotificationWatch()"
            print "        refreshMessageNotifications()"
            print "        MemoSync.startEventWatch(handleMessageNotificationEvent)"
            print "    }"
            print ""
            print "    function stopMessageNotificationWatch() {"
            print "        MemoSync.stopEventWatch()"
            print "    }"
        }
        function print_display_bridge_button_helpers() {
            print ""
            print "    property bool alarmButtonVisible: false"
            print "    property bool haButtonVisible: false"
            print "    property int buttonReadGeneration: 0"
            print "    property int buttonRetries: 0"
            print "    Timer {"
            print "        id: buttonRetryTimer"
            print "        repeat: false"
            print "        onTriggered: page.refreshDisplayBridgeButtons()"
            print "    }"
            print ""
            print "    function refreshDisplayBridgeButtons() {"
            print "        if (!page.visible) return"
            print "        buttonRetryTimer.stop()"
            print "        var generation = ++page.buttonReadGeneration"
            print "        HAConfig.homeButtons(function(alarmConfigured, dashboardAvailable, valid, reason, pages) {"
            print "            if (!page.visible || generation !== page.buttonReadGeneration) return"
            print "            if (!valid) {"
            print "                if (page.buttonRetries < 6) {"
            print "                    buttonRetryTimer.interval = 1000 * Math.pow(2, page.buttonRetries++)"
            print "                } else {"
            print "                    c300xDisplayPreferences.bridgeProblem = reason"
            print "                    buttonRetryTimer.interval = 300000"
            print "                }"
            print "                buttonRetryTimer.restart()"
            print "                return"
            print "            }"
            print "            page.buttonRetries = 0"
            print "            c300xDisplayPreferences.bridgeProblem = \"\""
            print "            c300xDisplayPreferences.bridgeShown = pages !== false"
            print "            page.alarmButtonVisible = alarmConfigured"
            print "            page.haButtonVisible = dashboardAvailable"
            print "        }, page)"
            print "    }"
            print ""
            print "    Image {"
            print "        id: c300xBridgeHint"
            print "        objectName: \"bridgeHint\""
            print "        visible: c300xDisplayPreferences.bridgeShown"
            print "        source: \"images/call/icon_call-home.svg\""
            print "        anchors.verticalCenter: header.verticalCenter"
            print "        x: (datecert.visible ? datecert.x + datecert.width : off.x + off.width) + page.width / 100 * 2"
            print "        Rectangle {"
            print "            visible: c300xDisplayPreferences.bridgeProblem !== \"\""
            print "            anchors.horizontalCenter: parent.right"
            print "            anchors.verticalCenter: parent.bottom"
            print "            width: 16"
            print "            height: 16"
            print "            radius: 8"
            print "            color: \"#f1c40f\""
            print "            Text {"
            print "                anchors.centerIn: parent"
            print "                text: \"!\""
            print "                color: \"#0a1c8c\""
            print "                font.pixelSize: 13"
            print "                font.bold: true"
            print "            }"
            print "        }"
            print "        BeepingMouseArea {"
            print "            anchors.fill: parent"
            print "            anchors.margins: -6"
            print "            onPressed: {"
            print "                c300xDisplayPreferences.openIntegration = true"
            print "                tabView.activateTab(settingsPage)"
            print "            }"
            print "        }"
            print "    }"
        }
        function print_home_assistant_button(name, flag, icon, description, target) {
            print "            BasicButton {"
            if (layout == "stock") {
                print "                id: " name
            }
            print "                objectName: \"" name "\""
            if (layout == "stock") {
                print "                visible: page." flag
            } else {
                print "                opacity: page." flag " ? 1 : 0"
                print "                enabled: page." flag
                if (name == "haButton") {
                    print "                x: buttonPrototype.width + foobar.spacing"
                }
            }
            print "                style: HomePageButtonStyle {"
            print "                    pressedImage: \"images/function_btn_p.svg\""
            print "                    pressedIcon: \"images/" icon "_p.svg\""
            print "                    defaultIcon: \"images/" icon ".svg\""
            print "                    defaultImage: \"images/function_btn.svg\""
            print "                    description: " description
            print "                }"
            print "                onTouched: tabView.activateTab(" target ")"
            print "            }"
        }
        function print_home_assistant_flow_item() {
            print ""
            if (layout != "stock") {
                print "            Item {"
                print "                id: displayBridgeButtonRow"
                print "                width: buttonPrototype.width * 2 + foobar.spacing"
                print "                height: buttonPrototype.height"
            }
            print_home_assistant_button("alarmButton", "alarmButtonVisible", "keylock_icon-small", "trsl.language === \"de\" ? \"Alarmanlage\" : (trsl.language === \"it\" ? \"Allarme\" : (trsl.language === \"fr\" ? \"Alarme\" : \"Alarm\"))", "alarmPage")
            print ""
            print_home_assistant_button("haButton", "haButtonVisible", "call/icon_call-home", "\"Home Assistant\"", "haPage")
            if (layout != "stock") {
                print "            }"
            }
        }
        function delta(line, opened, closed, copy) {
            copy=line
            opened=gsub(/\{/, "{", copy)
            copy=line
            closed=gsub(/\}/, "}", copy)
            return opened - closed
        }
        $0 == "import \"js/utils.js\" as Utils" {
            print
            print_memo_sync_import()
            next
        }
        $0 == "Page {" && !printed_memo_sync_import {
            print_memo_sync_import()
            print
            next
        }
        $0 == "    id: page" {
            print
            print_home_notification_helpers()
            print_display_bridge_button_helpers()
            next
        }
        $0 == "    property bool smallDateTimePresent: homeLinksModel.count > 0 || buttonHolder.buttonCount() > 2" {
            print "    onVisibleChanged: {"
            print "        if (visible) {"
            print "            page.refreshDisplayBridgeButtons()"
            print "            page.startMessageNotificationWatch()"
            print "        } else {"
            print "            ++page.buttonReadGeneration"
            print "            page.buttonRetries = 0"
            print "            buttonRetryTimer.stop()"
            print "            HAConfig.invalidateSharedRead(\"/ui/state\")"
            print "            stopMessageNotificationWatch()"
            print "        }"
            print "    }"
            print ""
            if (layout == "stock") {
                print
            } else {
                print "    property bool smallDateTimePresent: true"
            }
            next
        }
        $0 == "    function aboutToShow() {" {
            in_about_to_show=1
            print
            next
        }
        in_about_to_show && $0 == "    }" {
            print "        refreshDisplayBridgeButtons()"
            print "        refreshMessageNotifications()"
            print
            in_about_to_show=0
            next
        }
        $0 ~ /function buttonCount\(\)/ {
            in_button_count=1
            print
            next
        }
        in_button_count && layout == "stock" && $0 ~ /\+ 2$/ {
            sub(/\+ 2$/, "+ (page.alarmButtonVisible ? 1 : 0) + (page.haButtonVisible ? 1 : 0) + 2")
            print
            next
        }
        in_button_count && $0 ~ /\+ 2$/ {
            sub(/\+ 2$/, "+ (homeLinksModel.count > 0 ? 4 : 2)")
            print
            next
        }
        in_button_holder && layout != "stock" && $0 == "            flow: Flow.TopToBottom" {
            print "            flow: homeLinksModel.count > 0 ? Flow.LeftToRight : Flow.TopToBottom"
            print "            width: homeLinksModel.count > 0 ? buttonPrototype.width * 4 + spacing * 3 : undefined"
            next
        }
        in_button_holder && layout != "stock" && $0 == "                visible: buttonHolder.buttonCount() === 5" {
            print $0 " && homeLinksModel.count === 0"
            next
        }
        in_button_count && $0 ~ /^[[:space:]]*\}/ {
            in_button_count=0
            print
            next
        }
        $0 ~ /notificationsCount: answeringModel\.obj\.unreadMessages/ {
            sub(/answeringModel\.obj\.unreadMessages/, "page.unreadMessagesCount()")
            print
            next
        }
        $0 ~ /notificationsCount: answeringModel\.obj\.unreadMemos/ {
            sub(/answeringModel\.obj\.unreadMemos/, "page.unreadMemosCount()")
            print
            next
        }
        $0 == "                objectName: \"settingsButton\"" {
            in_settings_button=1
            print
            next
        }
        in_settings_button && $0 == "            }" {
            print
            print_home_assistant_flow_item()
            in_settings_button=0
            if (in_button_holder) {
                button_holder_depth += delta($0)
            }
            next
        }
        $0 == "    Item {" {
            maybe_button_holder=1
            maybe_button_holder_depth=1
            print
            next
        }
        maybe_button_holder && $0 == "        id: buttonHolder" {
            in_button_holder=1
            button_holder_depth=maybe_button_holder_depth
            maybe_button_holder=0
            print
            next
        }
        maybe_button_holder {
            maybe_button_holder=0
        }
        in_button_holder && button_holder_depth == 1 && $0 == "    }" {
            print
            in_button_holder=0
            next
        }
        {
            print
            if (in_button_holder) {
                button_holder_depth += delta($0)
            }
        }
    ' "$source_home_page" > "$temp_file"
    if [ "$layout" = "stock" ]; then
        verify_generated_page \
            "$temp_file" \
            "HomePage.qml" \
            'import "js/c300x_memos.js" as MemoSync' \
            'import "js/c300x_ha.js" as HAConfig' \
            'function refreshMessageNotifications()' \
            'property alias memoEventRetryTimer: memoRetryTimer' \
            'property string uiBaseUrl: c300xDisplayPreferences.uiBaseUrl' \
            'onTriggered: MemoSync.retryEventWatch()' \
            'HAConfig.homeButtons' \
            'id: c300xBridgeHint' \
            '+ (page.alarmButtonVisible ? 1 : 0) + (page.haButtonVisible ? 1 : 0) + 2' \
            'visible: page.alarmButtonVisible' \
            'visible: page.haButtonVisible' \
            'objectName: "alarmButton"' \
            'objectName: "haButton"' \
            'images/call/icon_call-home.svg'
    else
        verify_generated_page \
            "$temp_file" \
            "HomePage.qml" \
            'import "js/c300x_memos.js" as MemoSync' \
            'import "js/c300x_ha.js" as HAConfig' \
            'function refreshMessageNotifications()' \
            'property alias memoEventRetryTimer: memoRetryTimer' \
            'property string uiBaseUrl: c300xDisplayPreferences.uiBaseUrl' \
            'onTriggered: MemoSync.retryEventWatch()' \
            'HAConfig.homeButtons' \
            'id: c300xBridgeHint' \
            'id: displayBridgeButtonRow' \
            '+ (homeLinksModel.count > 0 ? 4 : 2)' \
            'flow: homeLinksModel.count > 0 ? Flow.LeftToRight : Flow.TopToBottom' \
            'width: homeLinksModel.count > 0 ? buttonPrototype.width * 4 + spacing * 3 : undefined' \
            'visible: buttonHolder.buttonCount() === 5 && homeLinksModel.count === 0' \
            'opacity: page.alarmButtonVisible ? 1 : 0' \
            'opacity: page.haButtonVisible ? 1 : 0' \
            'objectName: "alarmButton"' \
            'objectName: "haButton"' \
            'images/call/icon_call-home.svg'
    fi
    mv "$temp_file" "$home_page"
}

patch_memo_page() {
    output_dir="${PATCH_OUTPUT_DIR:-$GUI_DIR}"
    memo_page="$output_dir/MemoPage.qml"
    source_memo_page="$BACKUP_DIR/MemoPage.qml"
    temp_file="$output_dir/MemoPage.qml.tmp.$$"
    backup_file "MemoPage.qml"
    if [ ! -f "$source_memo_page" ]; then
        printf 'Missing original MemoPage.qml backup\n' >&2
        return 1
    fi
    mkdir -p "$output_dir"
    require_clean_original_page "$source_memo_page" "MemoPage.qml"
    awk '
        function print_memo_import() {
            if (!printed_import) {
                print "import \"js/c300x_memos.js\" as MemoSync"
                printed_import=1
            }
        }
        $0 == "import \"js/audiorecord.js\" as Utils" {
            print
            print_memo_import()
            next
        }
        $0 == "GridPage {" && !printed_import {
            print_memo_import()
            print
            next
        }
        $0 == "    topMargin: 86" {
            print "    property string uiBaseUrl: c300xDisplayPreferences.uiBaseUrl"
            print "    function aboutToShow() {"
            print "        MemoSync.syncMemoModel(page, AnsweringMessage.TextMemo)"
            print "    }"
            print ""
            print
            next
        }
        { print }
    ' "$source_memo_page" > "$temp_file"
    verify_generated_page \
        "$temp_file" \
        "MemoPage.qml" \
        'import "js/c300x_memos.js" as MemoSync' \
        'function aboutToShow()' \
        'MemoSync.syncMemoModel(page, AnsweringMessage.TextMemo)' \
        'property string uiBaseUrl: c300xDisplayPreferences.uiBaseUrl'
    mv "$temp_file" "$memo_page"
}

patch_call_block_popup() {
    output_dir="${PATCH_OUTPUT_DIR:-$GUI_DIR}"
    popup="$output_dir/Components/Settings/CallBlockPopup.qml"
    source_popup="$BACKUP_DIR/Components/Settings/CallBlockPopup.qml"
    temp_file="$output_dir/Components/Settings/CallBlockPopup.qml.tmp.$$"
    backup_file "Components/Settings/CallBlockPopup.qml"
    if [ ! -f "$source_popup" ]; then
        printf 'Missing original CallBlockPopup.qml backup\n' >&2
        return 1
    fi
    mkdir -p "$output_dir"
    require_clean_call_block_popup "$source_popup"
    awk '
        /message: qsTr\("Calls forwarded to the smartphones in the home"\)/ {
            sub(/message: qsTr\("Calls forwarded to the smartphones in the home"\) \+ trsl.empty/, "message: (trsl.language === \"de\" ? \"Anrufe an Home Assistant weitergeleitet\" : (trsl.language === \"it\" ? \"Chiamate inoltrate a Home Assistant\" : (trsl.language === \"fr\" ? \"Appels renvoyes vers Home Assistant\" : \"Calls forwarded to Home Assistant\"))) + trsl.empty")
            print
            message_patched=1
            next
        }
        /\/\/\{text: qsTr\("Forward calls to the smartphones in the home"\).*AnsweringMachine\.InHouseOnly/ {
            print "                    {text: (trsl.language === \"de\" ? \"Anrufe an Home Assistant\" : (trsl.language === \"it\" ? \"Inoltra chiamate a Home Assistant\" : (trsl.language === \"fr\" ? \"Renvoyer les appels vers Home Assistant\" : \"Forward calls to Home Assistant\"))) + trsl.empty, action: AnsweringMachine.InHouseOnly},"
            button_patched=1
            next
        }
        { print }
        END {
            if (!message_patched || !button_patched) {
                exit 12
            }
        }
    ' "$source_popup" > "$temp_file"
    verify_generated_page \
        "$temp_file" \
        "Components/Settings/CallBlockPopup.qml" \
        'case AnsweringMachine.InHouseOnly:' \
        'answeringMachine.ipcCallMode = action' \
        'Calls forwarded to Home Assistant' \
        'Forward calls to Home Assistant' \
        'action: AnsweringMachine.InHouseOnly'
    mv "$temp_file" "$popup"
}

patch_event_manager() {
    core_port="$(station_ui_port)"
    output_dir="${PATCH_OUTPUT_DIR:-$GUI_DIR}"
    event_manager="$output_dir/EventManager.qml"
    source_event_manager="$BACKUP_DIR/EventManager.qml"
    temp_file="$output_dir/EventManager.qml.tmp.$$"
    backup_file "EventManager.qml"
    if [ ! -f "$source_event_manager" ]; then
        printf 'Missing original EventManager.qml backup\n' >&2
        return 1
    fi
    mkdir -p "$output_dir"
    if grep -F -q 'function c300xNotifyMediaClosed()' "$source_event_manager"; then
        printf 'Refusing to patch EventManager.qml from an already patched source\n' >&2
        return 1
    fi
    awk -v port="$core_port" '
        $0 == "Item {" {
            print
            print ""
            print "    function c300xNotifyMediaClosed() {"
            print "        var request = new XMLHttpRequest()"
            print "        request.open(\"GET\", c300xRinger.uiBaseUrl + \"/ui/media-closed\", true)"
            print "        request.send()"
            print "    }"
            print ""
            print "    C300XRingerControl { id: c300xRinger; uiBaseUrl: \"http://127.0.0.1:" port "\" }"
            print "    property bool c300xCallActive: typeof intercomModel === \"undefined\" || intercomModel.isVideoCall || intercomModel.isIntercomCall || intercomModel.isSipIntercomCall"
            print "    property bool c300xRinging: false"
            print "    function c300xPreemptAlert() {"
            print "        if (typeof c300xAlerts !== \"undefined\") c300xAlerts.preempt()"
            print "    }"
            print "    function c300xAlertUserInteraction() {"
            print "        if (typeof c300xAlerts !== \"undefined\") c300xAlerts.userInteraction()"
            print "    }"
            next
        }
        /^        on(IncomingCall|CallStarted|CallAnswered|CallEnded|CallTypeChanged): \{$/ {
            print
            print "            c300xPreemptAlert()"
            if ($0 == "        onCallEnded: {") print "            c300xNotifyMediaClosed()"
            next
        }
        $0 == "        onRingtoneStarted: {" {
            print
            print "            c300xPreemptAlert()"
            print "            c300xRinging = true"
            next
        }
        $0 == "        onRingtoneFinished: {" {
            print
            print "            c300xPreemptAlert()"
            print "            c300xRinging = false"
            next
        }
        $0 == "        onScreenTurnedOn: {" {
            print
            print "            if (c300xCallActive || c300xRinging) c300xPreemptAlert()"
            next
        }
        /^        on(Pressed|Released): \{$/ {
            print
            print "            c300xAlertUserInteraction()"
            next
        }
        { print }
    ' "$source_event_manager" > "$temp_file"
    verify_generated_page \
        "$temp_file" \
        "EventManager.qml" \
        'function c300xNotifyMediaClosed()' \
        "C300XRingerControl { id: c300xRinger; uiBaseUrl: \"http://127.0.0.1:$core_port\" }" \
        'request.open("GET", c300xRinger.uiBaseUrl + "/ui/media-closed", true)' \
        'c300xNotifyMediaClosed()' \
        'onCallEnded:'
    mv "$temp_file" "$event_manager"
}

verify_alert_takeover_hooks() {
    # A partial/unknown vendor layout must not install an active alert receiver.
    awk '
        /^        on(IncomingCall|CallStarted|CallAnswered|CallEnded|CallTypeChanged|RingtoneStarted|RingtoneFinished): \{$/ {
            key=$1
            counts[key]++
            if ((getline next_line) <= 0 || next_line != "            c300xPreemptAlert()") bad=1
        }
        $0 == "        onScreenTurnedOn: {" {
            screens++
            if ((getline next_line) <= 0 || next_line != "            if (c300xCallActive || c300xRinging) c300xPreemptAlert()") bad=1
        }
        /^        on(Pressed|Released): \{$/ {
            keys++
            if ((getline next_line) <= 0 || next_line != "            c300xAlertUserInteraction()") bad=1
        }
        END {
            if (bad || screens != 1 || keys != 2 || counts["onIncomingCall:"] != 2 || counts["onCallAnswered:"] != 2 || counts["onCallEnded:"] != 2 || counts["onCallStarted:"] != 1 || counts["onCallTypeChanged:"] != 1 || counts["onRingtoneStarted:"] != 1 || counts["onRingtoneFinished:"] != 1) exit 12
        }
    ' "$1" || {
        printf 'Unsupported EventManager alert takeover hooks; active GUI unchanged\n' >&2
        return 1
    }
}

remove_obsolete_stock_source_files() {
    rm -f "$SOURCE_DIR/HomePage.qml" "$SOURCE_DIR/MemoPage.qml"
}

remove_obsolete_generated_icon_files() {
    rm -f \
        "$SOURCE_DIR/images/c300x_alarm_icon.svg" \
        "$SOURCE_DIR/images/c300x_alarm_icon_p.svg" \
        "$SOURCE_DIR/images/c300x_home_assistant_icon.svg" \
        "$SOURCE_DIR/images/c300x_home_assistant_icon_p.svg" \
        "$GUI_DIR/images/c300x_alarm_icon.svg" \
        "$GUI_DIR/images/c300x_alarm_icon_p.svg" \
        "$GUI_DIR/images/c300x_home_assistant_icon.svg" \
        "$GUI_DIR/images/c300x_home_assistant_icon_p.svg"
}

remove_obsolete_source_files() {
    rm -f \
        "$SOURCE_DIR/HomePage.qml" \
        "$SOURCE_DIR/MemoPage.qml" \
        "$SOURCE_DIR/images/c300x_alarm_icon.svg" \
        "$SOURCE_DIR/images/c300x_alarm_icon_p.svg" \
        "$SOURCE_DIR/images/c300x_home_assistant_icon.svg" \
        "$SOURCE_DIR/images/c300x_home_assistant_icon_p.svg"
}

remove_obsolete_gui_files() {
    for rel in $OBSOLETE_GUI_FILES; do
        rm -f "$GUI_DIR/$rel"
    done
}

cleanup_staging() {
    rm -rf "$STAGING_DIR"
}

generate_core_patch_stage() {
    cleanup_staging
    trap cleanup_staging EXIT
    mkdir -p "$STAGING_DIR"
    PATCH_OUTPUT_DIR="$STAGING_DIR"
    export PATCH_OUTPUT_DIR
    patch_event_manager
    copy_generated_file "C300XRingerControl.qml"
    copy_generated_file "js/c300x_ringer.js"
    unset PATCH_OUTPUT_DIR
}

copy_generated_feature_files() {
    for copy_rel in $GENERATED_FEATURE_FILES; do
        copy_generated_file "$copy_rel"
    done
}

generate_feature_patch_stage() {
    cleanup_staging
    trap cleanup_staging EXIT
    mkdir -p "$STAGING_DIR/js"
    PATCH_OUTPUT_DIR="$STAGING_DIR"
    export PATCH_OUTPUT_DIR
    patch_home_page
    patch_memo_page
    patch_general_settings
    copy_generated_feature_files
    patch_main_app
    unset PATCH_OUTPUT_DIR
}

generate_full_patch_stage() {
    cleanup_staging
    trap cleanup_staging EXIT
    mkdir -p "$STAGING_DIR/js"
    PATCH_OUTPUT_DIR="$STAGING_DIR"
    export PATCH_OUTPUT_DIR
    patch_event_manager
    verify_alert_takeover_hooks "$STAGING_DIR/EventManager.qml"
    copy_generated_file "C300XRingerControl.qml"
    copy_generated_file "js/c300x_ringer.js"
    patch_home_page
    patch_memo_page
    patch_general_settings
    copy_generated_feature_files
    patch_main_app
    unset PATCH_OUTPUT_DIR
}

generate_media_user_label_stage() {
    cleanup_staging
    trap cleanup_staging EXIT
    mkdir -p "$STAGING_DIR/Components/Settings"
    PATCH_OUTPUT_DIR="$STAGING_DIR"
    export PATCH_OUTPUT_DIR
    patch_call_block_popup
    unset PATCH_OUTPUT_DIR
}

apply_stage_changed_count() {
    changed=0
    for rel do
        if [ ! -f "$STAGING_DIR/$rel" ]; then
            printf 'Missing generated patch file: %s\n' "$rel" >&2
            return 1
        fi
        if [ ! -f "$GUI_DIR/$rel" ] || ! cmp -s "$STAGING_DIR/$rel" "$GUI_DIR/$rel"; then
            changed=$((changed + 1))
        fi
    done
    printf '%s\n' "$changed"
}

apply_feature_stage_changed_count() {
    changed="$(apply_stage_changed_count $FEATURE_PATCH_FILES)"
    for rel in $OBSOLETE_GUI_FILES; do
        if [ -e "$GUI_DIR/$rel" ]; then
            changed=$((changed + 1))
        fi
    done
    printf '%s\n' "$changed"
}

apply_full_stage_changed_count() {
    changed="$(apply_stage_changed_count $PATCH_FILES)"
    for rel in $OBSOLETE_GUI_FILES; do
        if [ -e "$GUI_DIR/$rel" ]; then
            changed=$((changed + 1))
        fi
    done
    printf '%s\n' "$changed"
}

copy_changed_patch_files() {
    for rel do
        if [ ! -f "$GUI_DIR/$rel" ] || ! cmp -s "$STAGING_DIR/$rel" "$GUI_DIR/$rel"; then
            mkdir -p "$(dirname "$GUI_DIR/$rel")"
            cp -p "$STAGING_DIR/$rel" "$GUI_DIR/$rel"
        fi
    done
}

copy_changed_feature_patch_files() {
    copy_changed_patch_files $FEATURE_PATCH_FILES
    remove_obsolete_gui_files
}

copy_changed_full_patch_files() {
    copy_changed_patch_files $PATCH_FILES
    remove_obsolete_gui_files
}

copy_changed_core_patch_files() {
    copy_changed_patch_files $CORE_PATCH_FILES
}

copy_changed_media_user_label_files() {
    copy_changed_patch_files $MEDIA_USER_LABEL_FILES
}

apply_generated_patch_if_changed() {
    changed_count="$1"
    shift
    if [ "$changed_count" -gt 0 ]; then
        run_write_action "$@"
    fi
}

station_ui_port() {
    port=${C300X_QML_UI_PORT-}
    if [ -z "$port" ]; then
        # Direct installs are not children of the running agent. Ask the native
        # config parser for its effective listener, never copy config into QML.
        config="${AGENT_BIN%/*}/config.json"
        if [ -f "$config" ]; then
            diagnosis="$("$AGENT_BIN" --config "$config" --diagnose-startup)" || return 1
            port="$(printf '%s\n' "$diagnosis" | sed -n 's/^    "ui_port": \([0-9][0-9]*\),$/\1/p')"
        else
            port=8090
        fi
    fi
    case "$port" in ""|0*|*[!0-9]*) echo "Invalid station UI port" >&2; return 1 ;; esac
    [ "${#port}" -le 5 ] && [ "$port" -le 65535 ] || return 1
    printf '%s\n' "$port"
}

patch_main_app() {
    output_dir="${PATCH_OUTPUT_DIR:-$GUI_DIR}"
    main_app="$output_dir/MainApp.qml"
    source_main_app="$BACKUP_DIR/MainApp.qml"
    temp_file="$output_dir/MainApp.qml.tmp.$$"
    backup_file "MainApp.qml"
    if [ ! -f "$source_main_app" ]; then
        printf 'Missing original MainApp.qml backup\n' >&2
        return 1
    fi
    mkdir -p "$output_dir"
    cp -p "$source_main_app" "$main_app"
    ui_port="$(station_ui_port)"
    awk -v port="$ui_port" '
        $0 == "import QtQuick 1.1" {
            print
            print "import \"js/c300x_ha.js\" as C300XPreferencesApi"
            print "import \"js/c300x_i18n.js\" as C300XPreferencesText"
            imports++
            next
        }
        $0 == "Item {" {
            print
            print "    C300XAlerts {"
            print "        id: c300xAlerts"
            print "        anchors.fill: parent"
            print "        z: 1000"
            print "        property variant activePage: tabView.current"
            print "        onActivePageChanged: userInteraction()"
            print "        blocked: typeof eventManager === \"undefined\" || eventManager.c300xCallActive === undefined || eventManager.c300xCallActive || eventManager.c300xRinging || !global.guiReadyToReceiveCalls || (activePage !== homePage && activePage !== haPage)"
            print "    }"
            print "    Item {"
            print "        id: c300xDisplayPreferences"
            print "        property string uiBaseUrl: \"http://127.0.0.1:" port "\""
            print "        property bool feedbackEnabled: true"
            print "        property string bridgeProblem: \"\""
            print "        property bool bridgeShown: true"
            print "        property bool openIntegration: false"
            print "        property bool ready: false"
            print "        property bool busy: false"
            print "        property bool stopped: false"
            print "        property bool touchToneEnabled: global.beepEnabled"
            print "        property bool applyingTouchTone: false"
            print "        property bool touchToneReportAgain: false"
            print "        property alias touchToneRetry: c300xTouchToneRetry"
            print "        property alias touchToneReportDeadline: c300xTouchToneDeadline"
            print "        function setTouchTone(value) { global.beepEnabled = value }"
            print "        onTouchToneEnabledChanged: if (!applyingTouchTone && !stopped) c300xTouchToneReport.restart()"
            print "        property string errorKey: \"\""
            print "        property string label: C300XPreferencesText.text(trsl.language, errorKey || \"ha_feedback_colors\") + trsl.empty"
            print "        property alias deadline: c300xPreferencesDeadline"
            print "        function load() { C300XPreferencesApi.loadDisplayPreferences(c300xDisplayPreferences) }"
            print "        function setFeedbackEnabled(value) { C300XPreferencesApi.saveDisplayPreferences(c300xDisplayPreferences, value) }"
            print "        Timer {"
            print "            id: c300xPreferencesDeadline"
            print "            interval: 5000"
            print "            repeat: false"
            print "            onTriggered: C300XPreferencesApi.cancelDisplayPreferences(c300xDisplayPreferences)"
            print "        }"
            print "        Timer {"
            print "            id: c300xTouchToneRetry"
            print "            interval: 30000"
            print "            onTriggered: C300XPreferencesApi.watchTouchTone(c300xDisplayPreferences)"
            print "        }"
            print "        Timer {"
            print "            id: c300xTouchToneReport"
            print "            interval: 0"
            print "            onTriggered: C300XPreferencesApi.reportTouchTone(c300xDisplayPreferences)"
            print "        }"
            print "        Timer {"
            print "            id: c300xTouchToneDeadline"
            print "            interval: 5000"
            print "            onTriggered: C300XPreferencesApi.retryTouchTone(c300xDisplayPreferences)"
            print "        }"
            print "        Component.onCompleted: { load(); C300XPreferencesApi.watchTouchTone(c300xDisplayPreferences) }"
            print "        Component.onDestruction: {"
            print "            stopped = true"
            print "            C300XPreferencesApi.cancelDisplayPreferences(c300xDisplayPreferences)"
            print "            C300XPreferencesApi.stopTouchTone(c300xDisplayPreferences)"
            print "        }"
            print "    }"
            roots++
            next
        }
        { print }
        END { if (imports != 1 || roots != 1) exit 12 }
    ' "$source_main_app" > "$temp_file"
    mv "$temp_file" "$main_app"
    if ! grep -q 'alarmPage,' "$main_app"; then
        awk '
            { print }
            $0 == "            memoPage," {
                print "            alarmPage,"
                print "            haPage,"
                inserted=1
            }
            END { if (!inserted) exit 10 }
        ' "$main_app" > "$temp_file"
        mv "$temp_file" "$main_app"
    fi
    if ! grep -q 'sourceUrl: "Alarm.qml"' "$main_app"; then
        awk '
            {
                if ($0 == "    PageLoader {") {
                    if ((getline next_line) <= 0) {
                        print
                        next
                    }
                    if (next_line == "        id: settingsPage" && !inserted) {
                        print "    PageLoader {"
                        print "        id: alarmPage"
                        print "        sourceUrl: \"Alarm.qml\""
                        print "    }"
                        print ""
                        print "    PageLoader {"
                        print "        id: haPage"
                        print "        sourceUrl: \"HomeAssistant.qml\""
                        print "    }"
                        print ""
                        inserted=1
                    }
                    print
                    print next_line
                    next
                }
                print
            }
            END { if (!inserted) exit 11 }
        ' "$main_app" > "$temp_file"
        mv "$temp_file" "$main_app"
    fi
    rm -f "$temp_file"
}

apply_core_patch_files() {
    generate_core_patch_stage
    changed_count="$(apply_stage_changed_count $CORE_PATCH_FILES)"
    apply_generated_patch_if_changed "$changed_count" copy_changed_core_patch_files
    cleanup_staging
}

apply_media_user_label_files() {
    generate_media_user_label_stage
    changed_count="$(apply_stage_changed_count $MEDIA_USER_LABEL_FILES)"
    apply_generated_patch_if_changed "$changed_count" copy_changed_media_user_label_files
    cleanup_staging
}

apply_feature_patch_files() {
    generate_feature_patch_stage
    changed_count="$(apply_feature_stage_changed_count)"
    apply_generated_patch_if_changed "$changed_count" copy_changed_feature_patch_files
    cleanup_staging
}

apply_patch_files() {
    generate_full_patch_stage
    changed_count="$(apply_full_stage_changed_count)"
    apply_generated_patch_if_changed "$changed_count" copy_changed_full_patch_files
    cleanup_staging
}

restore_file() {
    restore_rel="$1"
    restore_original="$BACKUP_DIR/$restore_rel"
    restore_dest="$GUI_DIR/$restore_rel"
    if [ -e "$restore_original" ]; then
        stock_backup_valid "$restore_rel" || return 1
        if [ -f "$restore_dest" ] && cmp -s "$restore_original" "$restore_dest"; then
            return 0
        fi
        mkdir -p "$(dirname "$restore_dest")"
        cp -p "$restore_original" "$restore_dest"
    elif is_generated_patch_file "$restore_rel"; then
        rm -f "$restore_dest"
    else
        printf 'No original backup available for %s; refusing to remove stock GUI file\n' "$restore_rel" >&2
        return 1
    fi
}

restore_changed_count() {
    check_settings_paths || return 1
    for rel in Settings.qml Components/Settings/GeneralsChoice.qml MainApp.qml HomePage.qml MemoPage.qml; do
        if [ -e "$BACKUP_DIR/$rel" ]; then
            stock_backup_valid "$rel" || return 1
        fi
    done
    changed=0
    if [ -e "$BACKUP_DIR/Components/Settings/GeneralsChoice.qml" ]; then
        if ! cmp -s "$BACKUP_DIR/Components/Settings/GeneralsChoice.qml" "$GUI_DIR/Components/Settings/GeneralsChoice.qml"; then
            changed=$((changed + 1))
        fi
    elif general_settings_partial_present; then
        printf 'No original backup available for Components/Settings/GeneralsChoice.qml; refusing to remove stock GUI file\n' >&2
        return 1
    fi
    if [ -f "$BACKUP_DIR/Settings.qml" ]; then
        cmp -s "$BACKUP_DIR/Settings.qml" "$GUI_DIR/Settings.qml" || changed=$((changed + 1))
    elif file_contains "$GUI_DIR/Settings.qml" c300xSettings; then
        echo "Missing original Settings.qml backup" >&2; return 1
    fi
    for rel in MainApp.qml HomePage.qml MemoPage.qml; do
        restore_original="$BACKUP_DIR/$rel"
        restore_dest="$GUI_DIR/$rel"
        if [ ! -e "$restore_original" ]; then
            if partial_patch_present; then
                printf 'No original backup available for %s; refusing to remove stock GUI file\n' "$rel" >&2
                return 1
            fi
            continue
        fi
        if [ ! -f "$restore_dest" ] || ! cmp -s "$restore_original" "$restore_dest"; then
            changed=$((changed + 1))
        fi
    done
    for rel in $GENERATED_FEATURE_FILES; do
        if [ -e "$GUI_DIR/$rel" ]; then
            changed=$((changed + 1))
        fi
    done
    for rel in $OBSOLETE_GUI_FILES; do
        if [ -e "$GUI_DIR/$rel" ]; then
            changed=$((changed + 1))
        fi
    done
    printf '%s\n' "$changed"
}

restore_core_changed_count() {
    changed=0
    restore_original="$BACKUP_DIR/EventManager.qml"
    restore_dest="$GUI_DIR/EventManager.qml"
    if [ ! -e "$restore_original" ]; then
        if core_partial_patch_present; then
            printf 'No original backup available for EventManager.qml; refusing to remove core media hook\n' >&2
            return 1
        fi
        printf '0\n'
        return 0
    fi
    stock_backup_valid EventManager.qml || return 1
    if [ ! -f "$restore_dest" ] || ! cmp -s "$restore_original" "$restore_dest"; then
        changed=$((changed + 1))
    fi
    if [ -e "$GUI_DIR/C300XRingerControl.qml" ]; then
        changed=$((changed + 1))
    fi
    if [ -e "$GUI_DIR/js/c300x_ringer.js" ]; then
        changed=$((changed + 1))
    fi
    printf '%s\n' "$changed"
}

is_generated_patch_file() {
    for known_rel in $GENERATED_FEATURE_FILES C300XRingerControl.qml js/c300x_ringer.js; do
        if [ "$1" = "$known_rel" ]; then
            return 0
        fi
    done
    return 1
}

restore_feature_stock_file() {
    restore_rel="$1"
    if [ -e "$BACKUP_DIR/$restore_rel" ] || partial_patch_present; then
        restore_file "$restore_rel"
    fi
}

restore_patch_files() {
    if [ -f "$BACKUP_DIR/Settings.qml" ]; then restore_file Settings.qml; fi
    if [ -e "$BACKUP_DIR/Components/Settings/GeneralsChoice.qml" ] || general_settings_partial_present; then
        restore_file "Components/Settings/GeneralsChoice.qml"
    fi
    restore_feature_stock_file "MainApp.qml"
    restore_feature_stock_file "HomePage.qml"
    restore_feature_stock_file "MemoPage.qml"
    for generated_rel in $GENERATED_FEATURE_FILES; do
        restore_file "$generated_rel"
    done
    remove_obsolete_gui_files
    REMOVE_EMPTY_JS=1
}

restore_media_user_label_changed_count() {
    restore_original="$BACKUP_DIR/Components/Settings/CallBlockPopup.qml"
    restore_dest="$GUI_DIR/Components/Settings/CallBlockPopup.qml"
    if [ ! -e "$restore_original" ]; then
        if media_user_label_partial_present; then
            printf 'No original backup available for Components/Settings/CallBlockPopup.qml; refusing to remove stock GUI file\n' >&2
            return 1
        fi
        printf '0\n'
        return 0
    fi
    stock_backup_valid Components/Settings/CallBlockPopup.qml || return 1
    if [ ! -f "$restore_dest" ] || ! cmp -s "$restore_original" "$restore_dest"; then
        printf '1\n'
    else
        printf '0\n'
    fi
}

restore_media_user_label_files() {
    if [ -e "$BACKUP_DIR/Components/Settings/CallBlockPopup.qml" ] || media_user_label_partial_present; then
        restore_file "Components/Settings/CallBlockPopup.qml"
    fi
}

restore_core_patch_files() {
    if [ -e "$BACKUP_DIR/EventManager.qml" ] || core_partial_patch_present; then
        restore_file "EventManager.qml"
    fi
    restore_file "C300XRingerControl.qml"
    restore_file "js/c300x_ringer.js"
    REMOVE_EMPTY_JS=1
}

restore_all_changed_count() {
    feature_changed_count="$(restore_changed_count)"
    core_changed_count="$(restore_core_changed_count)"
    media_user_label_changed_count="$(restore_media_user_label_changed_count)"
    printf '%s\n' "$((feature_changed_count + core_changed_count + media_user_label_changed_count))"
}

restore_all_patch_files() {
    restore_patch_files
    restore_core_patch_files
    restore_media_user_label_files
}

case "$ACTION" in
    status)
        transaction_report
        ;;
    recover)
        recover_transactions || true
        ;;
    apply|core-apply|media-user-label-apply|restore|core-restore|media-user-label-restore|restore-all)
        if ! recover_transactions; then
            printf 'An unfinished GUI write is still in place\n' >&2
            exit 1
        fi
        trap 'exit 130' HUP INT TERM
        ;;
esac

case "$ACTION" in
    status|recover)
        json_status
        ;;
    apply)
        apply_patch_files
        run_touch_phase apply
        json_write_status
        ;;
    core-apply)
        apply_core_patch_files
        json_write_status
        ;;
    media-user-label-apply)
        apply_media_user_label_files
        json_write_status
        ;;
    restore)
        changed_count="$(restore_changed_count)"
        if [ "$changed_count" -gt 0 ]; then
            run_write_action restore_patch_files
        fi
        run_touch_phase restore
        json_write_status
        ;;
    core-restore)
        changed_count="$(restore_core_changed_count)"
        if [ "$changed_count" -gt 0 ]; then
            run_write_action restore_core_patch_files
        fi
        json_write_status
        ;;
    media-user-label-restore)
        changed_count="$(restore_media_user_label_changed_count)"
        if [ "$changed_count" -gt 0 ]; then
            run_write_action restore_media_user_label_files
        fi
        json_write_status
        ;;
    restore-all)
        changed_count="$(restore_all_changed_count)"
        if [ "$changed_count" -gt 0 ]; then
            run_write_action restore_all_patch_files
        fi
        run_touch_phase restore
        json_write_status
        ;;
    reload)
        reload_gui
        json_status
        ;;
    *)
        printf '{"ok":false,"available":false,"state":"invalid_action"}\n'
        exit 2
        ;;
esac
