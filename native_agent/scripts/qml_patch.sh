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
DYNAMIC_HOME_PAGE="${C300X_QML_DYNAMIC_HOME_PAGE:-0}"
STAGING_DIR="${C300X_QML_STAGING_DIR:-${TMPDIR:-/tmp}/c300x-qml-patch.$$}"
CORE_PATCH_FILES="C300XRingerControl.qml js/c300x_ringer.js EventManager.qml"
MEDIA_USER_LABEL_FILES="Components/Settings/CallBlockPopup.qml"
# The display files this integration adds; every list of them derives from here.
GENERATED_FEATURE_FILES="Alarm.qml HomeAssistant.qml C300XEnergy.qml C300XEnergyConsumers.qml js/c300x_energy_consumers.js C300XPageNavigation.qml C300XAgenda.qml C300XLeaveHome.qml C300XChecks.qml C300XSituations.qml C300XOptionalPages.qml C300XDetailControl.qml C300XEnergyReadout.qml C300XEnergySums.qml C300XAlerts.qml js/c300x_alerts.js js/c300x_energy.js js/c300x_ha.js js/c300x_i18n.js js/c300x_memos.js"
FEATURE_PATCH_FILES="MainApp.qml HomePage.qml MemoPage.qml Components/Settings/GeneralsChoice.qml $GENERATED_FEATURE_FILES"
PATCH_FILES="$FEATURE_PATCH_FILES $CORE_PATCH_FILES"
QT5_VENDOR_FILES="EventManager.qml HomePage.qml MainApp.qml MemoPage.qml Components/Settings/GeneralsChoice.qml Components/Settings/CallBlockPopup.qml"
# Firmware 3.0.x has a Qt 5 display whose files are resources inside BtClass.
# The patch then works on a copy here; the changed files reach the display as
# a resource file that c300x-qrc-overlay.so, preloaded by the start script,
# registers ahead of the program's own.
QT5_DISPLAY=0
if [ -e "${C300X_QML_QT5_MARKER:-/usr/lib/libQt5Core.so.5}" ]; then
    QT5_DISPLAY=1
    QT5_AGENT_DIR="${C300X_AGENT_DIR:-/home/bticino/cfg/extra/c300x-native-agent}"
    QT5_BACKUP_ROOT="${C300X_BACKUP_ROOT:-/home/bticino/cfg/extra/c300x-device-file-backups}"
    QT5_ROOT="${C300X_QML_QT5_ROOT:-$QT5_AGENT_DIR/display-qt5}"
    QT5_RCC="${C300X_QML_QT5_RCC:-$QT5_AGENT_DIR/display-qt5.rcc}"
    QT5_OVERLAY_LIB="${C300X_QML_QT5_OVERLAY_LIB:-$QT5_AGENT_DIR/c300x-qrc-overlay.so}"
    QT5_WRAPPER_BACKUP="${C300X_QML_QT5_WRAPPER_BACKUP:-$QT5_BACKUP_ROOT/original/bin/BtClass_qws}"
    GUI_DIR="${C300X_QML_GUI_DIR:-$QT5_ROOT/skins/default}"
    BACKUP_DIR="${C300X_QML_BACKUP_DIR:-$QT5_BACKUP_ROOT/original/qt5/skins/default}"
fi
OBSOLETE_GUI_FILES="C300XText.qml C300XEnergyDistribution.qml images/c300x_alarm_icon.svg images/c300x_alarm_icon_p.svg images/c300x_home_assistant_icon.svg images/c300x_home_assistant_icon_p.svg"

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
    if [ -f "$BACKUP_DIR/MainApp.qml" ]; then
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
    qt5_fields=
    if [ "$QT5_DISPLAY" = "1" ]; then
        qt5_overlay="$(qt5_overlay_state)"
        # Left over from a run cut short: restore-all takes it away.
        if [ "$qt5_overlay" != "off" ] && [ "$state$core_state$media_user_label_state" = "originaloriginaloriginal" ]; then
            state=partial
            patched=null
        fi
        qt5_fields=",\"qt5_overlay\":\"$qt5_overlay\""
    fi
    if [ -n "$changed_files" ]; then
        printf '{"ok":true,"available":true,"state":"%s","patched":%s,"core_state":"%s","core_patched":%s,"media_user_label_state":"%s","media_user_label_patched":%s,"backup_available":%s,"core_backup_available":%s,"media_user_label_backup_available":%s,"gui_running":%s,"changed_files":%s%s}\n' "$state" "$patched" "$core_state" "$core_patched" "$media_user_label_state" "$media_user_label_patched" "$backup_available" "$core_backup_available" "$media_user_label_backup_available" "$gui_running" "$changed_files" "$qt5_fields"
    else
        printf '{"ok":true,"available":true,"state":"%s","patched":%s,"core_state":"%s","core_patched":%s,"media_user_label_state":"%s","media_user_label_patched":%s,"backup_available":%s,"core_backup_available":%s,"media_user_label_backup_available":%s,"gui_running":%s%s}\n' "$state" "$patched" "$core_state" "$core_patched" "$media_user_label_state" "$media_user_label_patched" "$backup_available" "$core_backup_available" "$media_user_label_backup_available" "$gui_running" "$qt5_fields"
    fi
}

json_reload_failed() {
    backup_available=false
    core_backup_available=false
    gui_running=false
    if [ -f "$BACKUP_DIR/MainApp.qml" ]; then
        backup_available=true
    fi
    if [ -f "$BACKUP_DIR/EventManager.qml" ]; then
        core_backup_available=true
    fi
    if command -v pidof >/dev/null 2>&1 && pidof BtClass >/dev/null 2>&1; then
        gui_running=true
    fi
    printf '{"ok":false,"available":true,"state":"reload_failed","patched":null,"core_state":"unknown","core_patched":null,"backup_available":%s,"core_backup_available":%s,"gui_running":%s}\n' "$backup_available" "$core_backup_available" "$gui_running"
}

file_contains() {
    file="$1"
    text="$2"
    [ -f "$file" ] && grep -F -q "$text" "$file"
}

full_patch_present() {
    file_contains "$GUI_DIR/MainApp.qml" 'sourceUrl: "Alarm.qml"' \
        && file_contains "$GUI_DIR/MainApp.qml" 'sourceUrl: "HomeAssistant.qml"' \
        && file_contains "$GUI_DIR/MainApp.qml" 'alarmPage,' \
        && file_contains "$GUI_DIR/MainApp.qml" 'haPage,' \
        && file_contains "$GUI_DIR/MainApp.qml" 'id: c300xDisplayPreferences' \
        && file_contains "$GUI_DIR/MainApp.qml" 'id: c300xAlerts' \
        && file_contains "$GUI_DIR/EventManager.qml" 'function c300xPreemptAlert()' \
        && general_settings_patch_present \
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
        || file_contains "$GUI_DIR/MemoPage.qml" 'MemoSync.syncMemoModel' \
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

general_settings_patch_present() {
    file_contains "$GUI_DIR/Components/Settings/GeneralsChoice.qml" 'id: c300xFeedbackSetting' \
        && file_contains "$GUI_DIR/Components/Settings/GeneralsChoice.qml" 'checked: c300xFeedbackSetting.visible ? c300xDisplayPreferences.feedbackEnabled : true' \
        && file_contains "$GUI_DIR/Components/Settings/GeneralsChoice.qml" 'onTouched: global.beepEnabled = checked'
}

general_settings_partial_present() {
    file_contains "$GUI_DIR/Components/Settings/GeneralsChoice.qml" 'c300xDisplayPreferences' \
        || file_contains "$GUI_DIR/Components/Settings/GeneralsChoice.qml" 'c300xFeedbackSetting'
}

home_page_feature_patch_present() {
    file_contains "$GUI_DIR/HomePage.qml" 'id: homeAssistantButtonRow' \
        || file_contains "$GUI_DIR/HomePage.qml" 'id: displayBridgeButtonRow' \
        || (
            file_contains "$GUI_DIR/HomePage.qml" 'function displayBridgeButtonCount()' \
            && file_contains "$GUI_DIR/HomePage.qml" 'HAConfig.homeButtons' \
            && file_contains "$GUI_DIR/HomePage.qml" '+ 2 + page.displayBridgeButtonCount()'
        )
}

core_patch_present() {
    file_contains "$GUI_DIR/EventManager.qml" 'function c300xNotifyMediaClosed()' \
        && file_contains "$GUI_DIR/EventManager.qml" 'request.open("GET", "http://127.0.0.1:8090/ui/media-closed", true)' \
        && file_contains "$GUI_DIR/EventManager.qml" 'C300XRingerControl {}' \
        && file_contains "$GUI_DIR/EventManager.qml" 'function c300xPreemptAlert()' \
        && cmp -s "$SOURCE_DIR/C300XRingerControl.qml" "$GUI_DIR/C300XRingerControl.qml" \
        && cmp -s "$SOURCE_DIR/js/c300x_ringer.js" "$GUI_DIR/js/c300x_ringer.js" \
        && core_call_end_hooks_present
}

core_partial_patch_present() {
    file_contains "$GUI_DIR/EventManager.qml" 'function c300xNotifyMediaClosed()' \
        || file_contains "$GUI_DIR/EventManager.qml" '/ui/media-closed' \
        || file_contains "$GUI_DIR/EventManager.qml" 'c300xNotifyMediaClosed()' \
        || file_contains "$GUI_DIR/EventManager.qml" 'C300XRingerControl {}' \
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
    # The swipe threshold patch is for the Qt 4 display library only.
    if [ "$QT5_DISPLAY" = "1" ]; then
        return 0
    fi
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
    mount -o remount,rw / >/dev/null 2>&1
}

remount_ro() {
    if [ "$NO_REMOUNT" = "1" ]; then
        return 0
    fi
    mount -o remount,ro / >/dev/null 2>&1
}

finish_write_action() {
    write_rc=$?
    trap - EXIT HUP INT TERM
    if [ "$write_rc" != "0" ]; then
        cleanup_staging
    fi
    recovery_ok=1
    restart_previous=0
    if [ "${WRITE_TRANSACTION_READY:-0}" = "1" ] && [ "${WRITE_TRANSACTION_COMMITTED:-0}" != "1" ]; then
        restart_previous="${WRITE_RELOAD_ATTEMPTED:-0}"
        for transaction_rel in $PATCH_FILES $MEDIA_USER_LABEL_FILES $OBSOLETE_GUI_FILES; do
            if [ -f "$WRITE_TRANSACTION/$transaction_rel" ]; then
                if ! mkdir -p "$(dirname "$GUI_DIR/$transaction_rel")" \
                    || ! mv -f "$WRITE_TRANSACTION/$transaction_rel" "$GUI_DIR/$transaction_rel"; then
                    recovery_ok=0
                fi
            else
                rm -f "$GUI_DIR/$transaction_rel" || recovery_ok=0
            fi
        done
        if [ "${QT5_PUBLISHED:-0}" = "1" ]; then
            if [ -f "$WRITE_TRANSACTION/.display-qt5.rcc" ]; then
                mv -f "$WRITE_TRANSACTION/.display-qt5.rcc" "$QT5_RCC" || recovery_ok=0
            else
                rm -f "$QT5_RCC" || recovery_ok=0
            fi
        fi
    fi
    if [ "$recovery_ok" = "1" ]; then
        if [ -n "${WRITE_TRANSACTION:-}" ]; then
            rm -rf "$WRITE_TRANSACTION" || write_rc=1
        fi
    else
        printf 'GUI rollback failed; recovery files retained in %s\n' "$WRITE_TRANSACTION" >&2
        write_rc=1
    fi
    if [ "${WRITE_TRANSACTION_COMMITTED:-0}" = "1" ] && [ "${REMOVE_EMPTY_JS:-0}" = "1" ]; then
        rmdir "$GUI_DIR/js" >/dev/null 2>&1 || true
    fi
    remount_ro || write_rc=1
    if [ "$restart_previous" = "1" ] && [ "$recovery_ok" = "1" ]; then
        if ! reload_gui; then
            printf 'Previous GUI files restored, but GUI restart could not be confirmed\n' >&2
        fi
    fi
    return "$write_rc"
}

abort_write_action() {
    finish_write_action || true
    exit 130
}

run_write_action() {
    WRITE_TRANSACTION=
    WRITE_TRANSACTION_READY=0
    WRITE_TRANSACTION_COMMITTED=0
    WRITE_RELOAD_ATTEMPTED=0
    REMOVE_EMPTY_JS=0
    QT5_PUBLISHED=0
    trap finish_write_action EXIT
    trap abort_write_action HUP INT TERM
    remount_rw
    if [ "$QT5_DISPLAY" = "1" ]; then
        mkdir -p "$GUI_DIR"
    fi
    # Keep recovery on the GUI filesystem so rollback needs no further copies.
    transaction_dir="$GUI_DIR/.c300x-qml-transaction.$$"
    (umask 077; mkdir "$transaction_dir")
    WRITE_TRANSACTION="$transaction_dir"
    for transaction_rel in $PATCH_FILES $MEDIA_USER_LABEL_FILES $OBSOLETE_GUI_FILES; do
        transaction_source="$GUI_DIR/$transaction_rel"
        if [ -L "$transaction_source" ] || { [ -e "$transaction_source" ] && [ ! -f "$transaction_source" ]; }; then
            printf 'Unsupported GUI file type: %s\n' "$transaction_source" >&2
            return 1
        fi
        if [ -f "$transaction_source" ]; then
            mkdir -p "$(dirname "$WRITE_TRANSACTION/$transaction_rel")"
            cp -p "$transaction_source" "$WRITE_TRANSACTION/$transaction_rel"
        fi
    done
    WRITE_TRANSACTION_READY=1
    "$@"
    qt5_publish
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

backup_file() {
    backup_rel="$1"
    backup_src="$GUI_DIR/$backup_rel"
    backup_dest="$BACKUP_DIR/$backup_rel"
    if [ -e "$backup_dest" ]; then
        return 0
    fi
    if [ ! -f "$backup_src" ]; then
        return 0
    fi
    case "$backup_rel" in
        HomePage.qml|MemoPage.qml)
            require_clean_original_page "$backup_src" "$backup_rel"
            ;;
        Components/Settings/CallBlockPopup.qml)
            require_clean_call_block_popup "$backup_src"
            ;;
        Components/Settings/GeneralsChoice.qml)
            require_clean_general_settings "$backup_src"
            ;;
        EventManager.qml)
            if grep -F -q 'function c300xNotifyMediaClosed()' "$backup_src"; then
                printf 'Refusing to back up an already patched EventManager.qml\n' >&2
                return 1
            fi
            ;;
        MainApp.qml)
            if grep -F -q 'sourceUrl: "Alarm.qml"' "$backup_src" \
                || grep -F -q 'sourceUrl: "HomeAssistant.qml"' "$backup_src" \
                || grep -F -q 'c300xDisplayPreferences' "$backup_src"; then
                printf 'Refusing to back up an already patched MainApp.qml\n' >&2
                return 1
            fi
            ;;
    esac
    mkdir -p "$(dirname "$backup_dest")"
    backup_temp_dir="$(mktemp -d "$backup_dest.tmp.XXXXXX")" || return 1
    if ! cp -p "$backup_src" "$backup_temp_dir/original" \
        || ! mv -f "$backup_temp_dir/original" "$backup_dest"; then
        rm -rf "$backup_temp_dir"
        return 1
    fi
    rmdir "$backup_temp_dir"
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
    install_file "$1" generated
}

require_clean_original_page() {
    page_file="$1"
    page_name="$2"
    [ -s "$page_file" ]
    if grep -F -q 'homeAssistantButtonRow' "$page_file" \
        || grep -F -q 'homeAssistantButtonColumn' "$page_file" \
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

patch_general_settings() {
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
    # Keep the vendor tone switch; make room for one native-style row below it.
    awk '
        $0 == "import QtQuick 1.1" { imports++ }
        $0 == "    anchors.topMargin: parent.height / 100 * 4" {
            print "    anchors.topMargin: 8"
            top_margins++
            next
        }
        !tone && $0 == "        spacing: 6" {
            print "        spacing: 4"
            column_spacing++
            next
        }
        $0 == "        id: beepButton" { tone++ }
        tone && $0 == "        anchors.topMargin: 32" {
            print "        anchors.topMargin: 8"
            margins++
            next
        }
        tone && $0 == "            id: space" { spacer = 1; print; next }
        spacer == 1 && $0 == "            width: 50" {
            print "            width: Math.max(0, buttonColumn.width - 40 - textBeep.width - selectorOnOff.width)"
            spacer = 2
            next
        }
        $0 == "            checked: global.beepEnabled" { checked++ }
        $0 == "            onTouched: global.beepEnabled = checked" { handler++ }
        $0 == "}" {
            roots++
            print ""
            print "    Item {"
            print "        id: c300xFeedbackSetting"
            print "        visible: typeof c300xDisplayPreferences !== \"undefined\""
            print "        anchors.horizontalCenter: parent.horizontalCenter"
            print "        anchors.top: beepButton.bottom"
            print "        anchors.topMargin: 6"
            print "        width: buttonColumn.width"
            print "        height: 44"
            print "        onVisibleChanged: if (visible) c300xDisplayPreferences.load()"
            print "        Component.onCompleted: if (visible) c300xDisplayPreferences.load()"
            print "        UbuntuLightText {"
            print "            anchors.left: parent.left"
            print "            anchors.leftMargin: 8"
            print "            anchors.right: c300xFeedbackSwitch.left"
            print "            anchors.rightMargin: 12"
            print "            anchors.verticalCenter: parent.verticalCenter"
            print "            text: c300xFeedbackSetting.visible ? c300xDisplayPreferences.label : \"\""
            print "            color: \"white\""
            print "            font.pixelSize: 18"
            print "            horizontalAlignment: Text.AlignLeft"
            print "            wrapMode: Text.WordWrap"
            print "        }"
            print "        BasicButton {"
            print "            id: c300xFeedbackSwitch"
            print "            anchors.right: parent.right"
            print "            anchors.rightMargin: 8"
            print "            anchors.verticalCenter: parent.verticalCenter"
            print "            enabled: c300xFeedbackSetting.visible && c300xDisplayPreferences.ready && !c300xDisplayPreferences.busy"
            print "            opacity: enabled ? 1 : 0.5"
            print "            checked: c300xFeedbackSetting.visible ? c300xDisplayPreferences.feedbackEnabled : true"
            print "            style: CheckableButtonStyle {"
            print "                defaultImage: \"../../images/ringtones/switch-bg_btn.svg\""
            print "                checkedImage: \"../../images/ringtones/switch-bg_btn_p.svg\""
            print "                defaultIconLeft: \"../../images/ringtones/switch_btn.svg\""
            print "                defaultIconRight: \"../../images/ringtones/disable_icon.svg\""
            print "                checkedIconLeft: \"../../images/ringtones/enable_icon.svg\""
            print "                checkedIconRight: \"../../images/ringtones/switch_btn_p.svg\""
            print "            }"
            print "            onTouched: c300xDisplayPreferences.setFeedbackEnabled(!c300xDisplayPreferences.feedbackEnabled)"
            print "        }"
            print "    }"
        }
        { print }
        END {
            if (imports != 1 || top_margins != 1 || column_spacing != 1 || tone != 1 || spacer != 2 || margins != 1 || checked != 1 || handler != 1 || roots != 1) {
                print "Unsupported original GeneralsChoice.qml layout" > "/dev/stderr"
                exit 12
            }
        }
    ' "$settings_original" > "$settings_output"
    verify_generated_page "$settings_output" "$settings_rel" \
        'anchors.top: beepButton.bottom' 'id: c300xFeedbackSetting' \
        'onTouched: global.beepEnabled = checked'
}

patch_home_page() {
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
    awk -v dynamic_home_page="$DYNAMIC_HOME_PAGE" '
        function print_memo_sync_import() {
            if (!printed_memo_sync_import) {
                print "import \"js/c300x_memos.js\" as MemoSync"
                if (dynamic_home_page == "1") {
                    print "import \"js/c300x_ha.js\" as HAConfig"
                }
                printed_memo_sync_import=1
            }
        }
        function print_home_notification_helpers() {
            print ""
            print "    property int externalUnreadMessages: -1"
            print "    property int externalUnreadMemos: -1"
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
            if (dynamic_home_page == "1") {
                print "        if (event && (event.topic === \"notifications\" || event.topic === \"display_bridge.state\")) {"
                print "            HAConfig.invalidateSharedRead(\"/ui/state\")"
                print "            refreshDisplayBridgeButtons()"
                print "        }"
            }
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
            if (dynamic_home_page != "1") {
                return
            }
            print ""
            print "    property bool alarmButtonVisible: false"
            print "    property bool haButtonVisible: false"
            print ""
            print "    function refreshDisplayBridgeButtons() {"
            print "        HAConfig.homeButtons(function(alarmConfigured, dashboardAvailable, valid) {"
            print "            if (!valid) return"
            print "            page.alarmButtonVisible = alarmConfigured"
            print "            page.haButtonVisible = dashboardAvailable"
            print "        })"
            print "    }"
        }
        function print_home_assistant_flow_item() {
            if (dynamic_home_page == "1") {
                print_home_assistant_dynamic_flow_items()
                return
            }
            print ""
            print "            Row {"
            print "                id: homeAssistantButtonRow"
            print "                width: buttonPrototype.width * 2 + foobar.spacing"
            print "                height: buttonPrototype.height"
            print "                spacing: foobar.spacing"
            print ""
            print "                BasicButton {"
            print "                    objectName: \"alarmButton\""
            print "                    style: HomePageButtonStyle {"
            print "                        pressedImage: \"images/function_btn_p.svg\""
            print "                        pressedIcon: \"images/keylock_icon-small_p.svg\""
            print "                        defaultIcon: \"images/keylock_icon-small.svg\""
            print "                        defaultImage: \"images/function_btn.svg\""
            print "                        description: trsl.language === \"de\" ? \"Alarmanlage\" : (trsl.language === \"it\" ? \"Allarme\" : (trsl.language === \"fr\" ? \"Alarme\" : \"Alarm\"))"
            print "                    }"
            print "                    onTouched: tabView.activateTab(alarmPage)"
            print "                }"
            print ""
            print "                BasicButton {"
            print "                    objectName: \"haButton\""
            print "                    style: HomePageButtonStyle {"
            print "                        pressedImage: \"images/function_btn_p.svg\""
            print "                        pressedIcon: \"images/call/icon_call-home_p.svg\""
            print "                        defaultIcon: \"images/call/icon_call-home.svg\""
            print "                        defaultImage: \"images/function_btn.svg\""
            print "                        description: \"Home Assistant\""
            print "                    }"
            print "                    onTouched: tabView.activateTab(haPage)"
            print "                }"
            print "            }"
        }
        function print_home_assistant_dynamic_flow_items() {
            print ""
            print "            Row {"
            print "                id: displayBridgeButtonRow"
            print "                width: buttonPrototype.width * 2 + foobar.spacing"
            print "                height: buttonPrototype.height"
            print "                spacing: foobar.spacing"
            print "            BasicButton {"
            print "                objectName: \"alarmButton\""
            print "                opacity: page.alarmButtonVisible ? 1 : 0"
            print "                enabled: page.alarmButtonVisible"
            print "                style: HomePageButtonStyle {"
            print "                    pressedImage: \"images/function_btn_p.svg\""
            print "                    pressedIcon: \"images/keylock_icon-small_p.svg\""
            print "                    defaultIcon: \"images/keylock_icon-small.svg\""
            print "                    defaultImage: \"images/function_btn.svg\""
            print "                    description: trsl.language === \"de\" ? \"Alarmanlage\" : (trsl.language === \"it\" ? \"Allarme\" : (trsl.language === \"fr\" ? \"Alarme\" : \"Alarm\"))"
            print "                }"
            print "                onTouched: tabView.activateTab(alarmPage)"
            print "            }"
            print ""
            print "            BasicButton {"
            print "                objectName: \"haButton\""
            print "                opacity: page.haButtonVisible ? 1 : 0"
            print "                enabled: page.haButtonVisible"
            print "                style: HomePageButtonStyle {"
            print "                    pressedImage: \"images/function_btn_p.svg\""
            print "                    pressedIcon: \"images/call/icon_call-home_p.svg\""
            print "                    defaultIcon: \"images/call/icon_call-home.svg\""
            print "                    defaultImage: \"images/function_btn.svg\""
            print "                    description: \"Home Assistant\""
            print "                }"
            print "                onTouched: tabView.activateTab(haPage)"
            print "            }"
            print "            }"
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
            print "        if (!visible) {"
            print "            stopMessageNotificationWatch()"
            print "        }"
            print "    }"
            print ""
            print
            next
        }
        $0 == "    function aboutToShow() {" {
            in_about_to_show=1
            print
            next
        }
        in_about_to_show && $0 == "    }" {
            if (dynamic_home_page == "1") {
                print "        refreshDisplayBridgeButtons()"
            }
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
        in_button_count && $0 ~ /^[[:space:]]*\}/ {
            in_button_count=0
            print
            next
        }
        $0 == "                loader.item.setDate()" {
            print
            if (dynamic_home_page == "1") {
                print "                refreshDisplayBridgeButtons()"
            }
            print "                startMessageNotificationWatch()"
            next
        }
        $0 == "            } else {" {
            print
            print "                stopMessageNotificationWatch()"
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
    if [ "$DYNAMIC_HOME_PAGE" = "1" ]; then
        verify_generated_page \
            "$temp_file" \
            "HomePage.qml" \
            'import "js/c300x_memos.js" as MemoSync' \
            'import "js/c300x_ha.js" as HAConfig' \
            'function refreshMessageNotifications()' \
            'property alias memoEventRetryTimer: memoRetryTimer' \
            'onTriggered: MemoSync.retryEventWatch()' \
            'HAConfig.homeButtons' \
            'opacity: page.alarmButtonVisible ? 1 : 0' \
            'opacity: page.haButtonVisible ? 1 : 0' \
            'objectName: "alarmButton"' \
            'objectName: "haButton"' \
            'images/call/icon_call-home.svg'
    else
        verify_generated_page \
            "$temp_file" \
            "HomePage.qml" \
            'import "js/c300x_memos.js" as MemoSync' \
            'function refreshMessageNotifications()' \
            'property alias memoEventRetryTimer: memoRetryTimer' \
            'onTriggered: MemoSync.retryEventWatch()' \
            'function startMessageNotificationWatch()' \
            'MemoSync.syncHomeNotifications(page)' \
            'id: homeAssistantButtonRow' \
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
        'MemoSync.syncMemoModel(page, AnsweringMessage.TextMemo)'
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
    awk '
        $0 == "Item {" {
            print
            print ""
            print "    function c300xNotifyMediaClosed() {"
            print "        var request = new XMLHttpRequest()"
            print "        request.open(\"GET\", \"http://127.0.0.1:8090/ui/media-closed\", true)"
            print "        request.send()"
            print "    }"
            print ""
            print "    C300XRingerControl {}"
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
        'C300XRingerControl {}' \
        'request.open("GET", "http://127.0.0.1:8090/ui/media-closed", true)' \
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

# Firmware 3.0.x (Qt 5) writes the handlers in Connections as functions; the
# patch reads the older form, which Qt 5 still runs.
qt5_normalize() {
    awk '
        NR == 1 && $0 == "import QtQuick 2.7" { print "import QtQuick 1.1"; next }
        {
            line = $0
            if (top > 0 && kind[top] == "c" && line ~ /^ *function on[A-Z][A-Za-z]* *\(/) {
                indent = line; sub(/[^ ].*$/, "", indent)
                name = line; sub(/^ *function /, "", name); sub(/[ (].*$/, "", name)
                rest = line; sub(/^[^)]*\) */, "", rest)
                line = indent name ":" (rest == "" ? "" : " " rest)
                converted++
            }
            connections = $0 ~ /^ *Connections *\{/
            for (i = 1; i <= length($0); i++) {
                ch = substr($0, i, 1)
                if (ch == "{") { top++; kind[top] = connections ? "c" : "o"; connections = 0 }
                else if (ch == "}" && top > 0) top--
            }
            print line
        }
    '
}

qt5_import() {
    import_dir="$1"
    for rel in $QT5_VENDOR_FILES; do
        if [ ! -s "$import_dir/$rel" ]; then
            printf 'Missing Qt 5 display file: %s\n' "$rel" >&2
            return 1
        fi
    done
    for rel in $QT5_VENDOR_FILES; do
        # A working copy is kept: it may carry the patch already.
        [ -e "$GUI_DIR/$rel" ] && continue
        mkdir -p "$(dirname "$GUI_DIR/$rel")"
        qt5_normalize < "$import_dir/$rel" > "$GUI_DIR/$rel.tmp"
        if ! head -n 1 "$GUI_DIR/$rel.tmp" | grep -qx 'import QtQuick 1.1'; then
            rm -f "$GUI_DIR/$rel.tmp"
            printf 'Unsupported Qt 5 display file: %s\n' "$rel" >&2
            return 1
        fi
        mv "$GUI_DIR/$rel.tmp" "$GUI_DIR/$rel"
    done
}

# Read afresh on every change: a copy made for another firmware is dropped
# together with its originals.
qt5_prepare() {
    if [ "$QT5_DISPLAY" != "1" ]; then
        return 0
    fi
    rm -rf "$QT5_ROOT/vendor.new"
    qt5_result="$("$AGENT_BIN" --display-qt5 extract "$QT5_ROOT/vendor.new" $QT5_VENDOR_FILES 2>/dev/null || true)"
    case "$qt5_result" in
        *'"ok":true'*) ;;
        *)
            rm -rf "$QT5_ROOT/vendor.new"
            printf 'Cannot read the display files of this firmware: %s\n' "$qt5_result" >&2
            return 1
            ;;
    esac
    for rel in $QT5_VENDOR_FILES; do
        if [ -d "$QT5_ROOT/vendor" ] && ! cmp -s "$QT5_ROOT/vendor/$rel" "$QT5_ROOT/vendor.new/$rel"; then
            rm -rf "$QT5_ROOT/vendor" "$GUI_DIR" "$BACKUP_DIR"
            break
        fi
    done
    rm -rf "$QT5_ROOT/vendor"
    mv "$QT5_ROOT/vendor.new" "$QT5_ROOT/vendor"
    mkdir -p "$GUI_DIR"
    qt5_import "$QT5_ROOT/vendor"
}

qt5_overlay_state() {
    if [ -e "$QT5_RCC.failed" ]; then
        printf 'failed\n'
    elif [ -f "$QT5_RCC" ] || grep -q 'c300x-qrc-overlay' "$GUI_WRAPPER" 2>/dev/null; then
        printf 'active\n'
    else
        printf 'off\n'
    fi
}

# The vendor start script with the overlay ahead of the plain start. A display
# that ends with an error within a minute of starting with the overlay marks it
# failed and starts as shipped; the next change of the patch clears the mark.
qt5_wrapper_text() {
    awk -v lib="$QT5_OVERLAY_LIB" -v rcc="$QT5_RCC" '
        $0 == "./bin/gui/BtClass &" && !done {
            print "# c300x-qrc-overlay: display pages of the Home Assistant integration"
            print "if [ -f \047" lib "\047 ] && [ -f \047" rcc "\047 ] && [ ! -e \047" rcc ".failed\047 ]; then"
            print "    c300x_start=$(date +%s)"
            print "    LD_PRELOAD=\047" lib "\047 C300X_QRC_OVERLAY=\047" rcc "\047 QML_DISABLE_DISK_CACHE=1 ./bin/gui/BtClass &"
            print "    wait $!"
            print "    c300x_rc=$?"
            print "    case $c300x_rc in 0|137|138|140|143) exit $c300x_rc ;; esac"
            print "    [ $(($(date +%s) - c300x_start)) -lt 60 ] || exit $c300x_rc"
            print "    : > \047" rcc ".failed\047"
            print "fi"
            done = 1
        }
        { print }
        END { if (!done) exit 1 }
    ' "$QT5_WRAPPER_BACKUP"
}

qt5_wrapper_install() {
    if ! grep -q 'c300x-qrc-overlay' "$GUI_WRAPPER"; then
        mkdir -p "$(dirname "$QT5_WRAPPER_BACKUP")"
        cp -p "$GUI_WRAPPER" "$QT5_WRAPPER_BACKUP.tmp"
        mv -f "$QT5_WRAPPER_BACKUP.tmp" "$QT5_WRAPPER_BACKUP"
    fi
    if [ ! -f "$QT5_WRAPPER_BACKUP" ] || ! qt5_wrapper_text > "$GUI_WRAPPER.c300x.tmp"; then
        rm -f "$GUI_WRAPPER.c300x.tmp"
        printf 'Unsupported display start script: %s\n' "$GUI_WRAPPER" >&2
        return 1
    fi
    if cmp -s "$GUI_WRAPPER.c300x.tmp" "$GUI_WRAPPER"; then
        rm -f "$GUI_WRAPPER.c300x.tmp"
        return 0
    fi
    chmod 755 "$GUI_WRAPPER.c300x.tmp"
    mv -f "$GUI_WRAPPER.c300x.tmp" "$GUI_WRAPPER"
}

qt5_wrapper_restore() {
    if ! grep -q 'c300x-qrc-overlay' "$GUI_WRAPPER" 2>/dev/null; then
        return 0
    fi
    if [ ! -f "$QT5_WRAPPER_BACKUP" ]; then
        printf 'No original of the display start script: %s\n' "$QT5_WRAPPER_BACKUP" >&2
        return 1
    fi
    cp -p "$QT5_WRAPPER_BACKUP" "$GUI_WRAPPER.c300x.tmp"
    mv -f "$GUI_WRAPPER.c300x.tmp" "$GUI_WRAPPER"
}

# Every file that differs from the firmware's, back in Qt 5 form, into the
# resource file; with none left the start script is the vendor one again.
qt5_publish() {
    if [ "$QT5_DISPLAY" != "1" ]; then
        return 0
    fi
    qt5_stage="$QT5_ROOT/rcc-stage.$$"
    rm -rf "$qt5_stage"
    mkdir -p "$qt5_stage"
    qt5_files=
    for rel in $PATCH_FILES $MEDIA_USER_LABEL_FILES; do
        if [ ! -f "$GUI_DIR/$rel" ]; then
            continue
        fi
        if [ -f "$QT5_ROOT/vendor/$rel" ]; then
            qt5_normalize < "$QT5_ROOT/vendor/$rel" > "$qt5_stage/.original"
            if cmp -s "$qt5_stage/.original" "$GUI_DIR/$rel"; then
                continue
            fi
        fi
        mkdir -p "$(dirname "$qt5_stage/$rel")"
        sed 's/^import QtQuick 1\.1$/import QtQuick 2.7/' "$GUI_DIR/$rel" > "$qt5_stage/$rel"
        qt5_files="$qt5_files $rel"
    done
    rm -f "$qt5_stage/.original"
    if [ -f "$QT5_RCC" ]; then
        cp -p "$QT5_RCC" "$WRITE_TRANSACTION/.display-qt5.rcc"
    fi
    QT5_PUBLISHED=1
    if [ -z "$qt5_files" ]; then
        rm -rf "$qt5_stage"
        rm -f "$QT5_RCC" "$QT5_RCC.failed"
        qt5_wrapper_restore
        return
    fi
    qt5_result="$("$AGENT_BIN" --display-qt5 pack "$qt5_stage" "$QT5_RCC" $qt5_files 2>/dev/null || true)"
    rm -rf "$qt5_stage"
    case "$qt5_result" in
        *'"ok":true'*) ;;
        *)
            printf 'Cannot write the display resource file: %s\n' "$qt5_result" >&2
            return 1
            ;;
    esac
    rm -f "$QT5_RCC.failed"
    qt5_wrapper_install
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
    awk '
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
            print "        property bool feedbackEnabled: true"
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
    changed=0
    if [ -e "$BACKUP_DIR/Components/Settings/GeneralsChoice.qml" ]; then
        if ! cmp -s "$BACKUP_DIR/Components/Settings/GeneralsChoice.qml" "$GUI_DIR/Components/Settings/GeneralsChoice.qml"; then
            changed=$((changed + 1))
        fi
    elif general_settings_partial_present; then
        printf 'No original backup available for Components/Settings/GeneralsChoice.qml; refusing to remove stock GUI file\n' >&2
        return 1
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
        json_status
        ;;
    apply)
        qt5_prepare
        apply_patch_files
        touch_patch apply
        json_write_status
        ;;
    core-apply)
        qt5_prepare
        apply_core_patch_files
        json_write_status
        ;;
    media-user-label-apply)
        qt5_prepare
        apply_media_user_label_files
        json_write_status
        ;;
    restore)
        changed_count="$(restore_changed_count)"
        if [ "$changed_count" -gt 0 ]; then
            run_write_action restore_patch_files
        fi
        touch_patch restore
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
        if [ "$changed_count" -gt 0 ] || { [ "$QT5_DISPLAY" = "1" ] && [ "$(qt5_overlay_state)" != "off" ]; }; then
            run_write_action restore_all_patch_files
        fi
        touch_patch restore
        json_write_status
        ;;
    reload)
        reload_gui
        json_status
        ;;
    qt5-import)
        qt5_import "${2:?}"
        json_status
        ;;
    *)
        printf '{"ok":false,"available":false,"state":"invalid_action"}\n'
        exit 2
        ;;
esac
