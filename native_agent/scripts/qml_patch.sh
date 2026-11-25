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
GUI_STOP_SECONDS="${C300X_QML_GUI_STOP_SECONDS:-10}"
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
QT5_VENDOR_FILES="EventManager.qml HomePage.qml MainApp.qml MemoPage.qml Settings.qml Components/Settings/GeneralsChoice.qml Components/Settings/CallBlockPopup.qml"
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
    QT5_LOG="${C300X_QML_QT5_LOG:-/tmp/c300x-display-qt5.log}"
    QT5_BOOT_ID="${C300X_QML_BOOT_ID:-/proc/sys/kernel/random/boot_id}"
    # bt_daemon checks the watchdog file at least every 32 s and reboots
    # without it: a display that wrote none within 40 s is not starting.
    QT5_START_SECONDS="${C300X_QML_QT5_START_SECONDS:-40}"
    QT5_STABLE_SECONDS="${C300X_QML_QT5_STABLE_SECONDS:-8}"
    QT5_ALIVE_FILE="${C300X_QML_GUI_ALIVE_FILE:-/var/tmp/bticino/bt_wd/BtClass_qws}"
    # The Qt 5 restart: one worker in a session of its own serves the requests.
    GUI_RUN_DIR="${C300X_QML_GUI_RUN_DIR:-${TMPDIR:-/tmp}/c300x-gui-restart}"
    GUI_BUDGET_SECONDS="${C300X_QML_GUI_BUDGET_SECONDS:-24}"
    GUI_FLOCK="${C300X_QML_GUI_FLOCK:-flock}"
    GUI_SHELL="${C300X_QML_SHELL:-sh}"
    GUI_WRAPPER_NAME="${GUI_WRAPPER##*/}"
    GUI_REQUESTS=0
    SCRIPT_STARTED="$(date +%s)"
    QT5_UNSUPPORTED="$QT5_ROOT/unsupported"
    GUI_DIR="${C300X_QML_GUI_DIR:-$QT5_ROOT/skins/default}"
    BACKUP_DIR="${C300X_QML_BACKUP_DIR:-$QT5_BACKUP_ROOT/original/qt5/skins/default}"
fi
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
    qt5_fields=
    if [ "$QT5_DISPLAY" = "1" ]; then
        # A request nobody serves (its worker died, or no requester waits any
        # more) is taken up by the next status read.
        gui_restart=idle
        if [ -d "$GUI_RUN_DIR/requests" ] && gui_requests_waiting; then
            gui_spawn_worker
            gui_restart=pending
        elif [ -e "$GUI_RUN_DIR/lock" ] && command -v "$GUI_FLOCK" >/dev/null 2>&1 \
            && ! "$GUI_FLOCK" -n "$GUI_RUN_DIR/lock" true 2>/dev/null; then
            gui_restart=pending
        fi
        qt5_overlay="$(qt5_overlay_state)"
        # Left over from a run cut short: restore-all takes it away.
        if [ "$qt5_overlay" != "off" ] && [ "$state$core_state$media_user_label_state" = "originaloriginaloriginal" ]; then
            state=partial
            patched=null
        fi
        # pending: a display restart is still queued or running; its outcome
        # (gui_running, qt5_overlay) shows in a status read after it.
        qt5_fields=",\"qt5_overlay\":\"$qt5_overlay\",\"gui_restart\":\"$gui_restart\""
        if [ -s "$QT5_UNSUPPORTED" ]; then
            qt5_fields="$qt5_fields,\"qt5_unsupported\":\"$(tr -cd 'a-z0-9_' < "$QT5_UNSUPPORTED" | head -c 48)\""
        fi
    fi
    home_buttons="$(installed_home_buttons)"
    if [ "$QT5_DISPLAY" = "1" ] && [ "$qt5_overlay" != "active" ]; then
        home_buttons=null
    fi
    transaction_field=
    if [ -n "$TRANSACTION_STATE" ]; then
        transaction_field=",\"transaction\":\"$TRANSACTION_STATE\""
    fi
    if [ -n "$changed_files" ]; then
        printf '{"ok":true,"available":true,"state":"%s","patched":%s,"core_state":"%s","core_patched":%s,"media_user_label_state":"%s","media_user_label_patched":%s,"backup_available":%s,"core_backup_available":%s,"media_user_label_backup_available":%s,"gui_running":%s,"home_buttons":%s,"changed_files":%s%s%s}\n' "$state" "$patched" "$core_state" "$core_patched" "$media_user_label_state" "$media_user_label_patched" "$backup_available" "$core_backup_available" "$media_user_label_backup_available" "$gui_running" "$home_buttons" "$changed_files" "$qt5_fields" "$transaction_field"
    else
        printf '{"ok":true,"available":true,"state":"%s","patched":%s,"core_state":"%s","core_patched":%s,"media_user_label_state":"%s","media_user_label_patched":%s,"backup_available":%s,"core_backup_available":%s,"media_user_label_backup_available":%s,"gui_running":%s,"home_buttons":%s%s%s}\n' "$state" "$patched" "$core_state" "$core_patched" "$media_user_label_state" "$media_user_label_patched" "$backup_available" "$core_backup_available" "$media_user_label_backup_available" "$gui_running" "$home_buttons" "$qt5_fields" "$transaction_field"
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

# A zombie has ended: bt_daemon, which started the first start script, may
# never reap it.
gui_pids_alive() {
    for gui_pid in $1; do
        kill -0 "$gui_pid" 2>/dev/null || continue
        gui_state="$(sed -n 's/^.*) \(.\).*$/\1/p' "$PROC_DIR/$gui_pid/stat" 2>/dev/null || true)"
        [ "$gui_state" = "Z" ] || return 0
    done
    return 1
}

gui_wait_gone() {
    gui_waited=0
    while gui_pids_alive "$1"; do
        if [ "$gui_waited" -ge "$2" ]; then
            return 1
        fi
        sleep 1
        gui_waited=$((gui_waited + 1))
    done
}

gui_pids() {
    if [ "$1" = BtClass ]; then
        pidof BtClass 2>/dev/null || true
    else
        # A start script runs as "sh <script>": only pidof -x names it.
        pidof -x "$1" 2>/dev/null || pidof "$1" 2>/dev/null || true
    fi
}

gui_phase() {
    printf '%s\n' "$1" > "$GUI_RUN_DIR/phase" 2>/dev/null || true
}

# Every start script process and display program ends before anything starts:
# a start script that does not end gets SIGKILL, so no trap of it runs later.
gui_stop() {
    gui_old="$(gui_pids "$GUI_WRAPPER_NAME") $(gui_pids BtClass)"
    killall "$GUI_WRAPPER_NAME" >/dev/null 2>&1 || true
    killall BtClass >/dev/null 2>&1 || true
    if gui_wait_gone "$gui_old" "$GUI_STOP_SECONDS"; then
        return 0
    fi
    for gui_pid in $gui_old; do
        kill -KILL "$gui_pid" >/dev/null 2>&1 || true
    done
    gui_wait_gone "$gui_old" 3
}

gui_settle() {
    : > "$GUI_RUN_DIR/started"
    gui_phase settle
    # At least one second: the watchdog file of the new program is then newer.
    if [ "$GUI_RELOAD_DELAY_SECONDS" -ge 1 ]; then
        sleep "$GUI_RELOAD_DELAY_SECONDS"
    else
        sleep 1
    fi
}

gui_start() {
    gui_phase start
    [ -f "$1" ] || return 1
    gui_session=
    if command -v setsid >/dev/null 2>&1; then
        gui_session=setsid
    fi
    gui_shell=/bin/sh
    if [ -x "$1" ]; then
        gui_shell=
    fi
    (
        cd "$GUI_ROOT" || exit 1
        exec 9>&- 8>&-
        $gui_session $gui_shell "$1" </dev/null >/tmp/BtClass_qws.agent.log 2>&1 &
    )
}

# gui_result: ready (the display program wrote its watchdog file after the
# start and the same program kept running QT5_STABLE_SECONDS after that),
# overlay_failed (the start script marked the overlay and went on as shipped)
# or failed (no start script and no display program left, or no watchdog
# write within QT5_START_SECONDS).
gui_verify() {
    gui_phase verify
    gui_had_mark=
    gui_waited=0
    gui_alive_at=
    gui_seen_pid=
    gui_stamp="$GUI_RUN_DIR/started"
    # Verified again without a new start (the shipped display after a failed
    # overlay): writes of the program before do not count.
    if [ "${1:-}" = "again" ]; then
        gui_stamp="$GUI_RUN_DIR/seen"
        : > "$gui_stamp"
    fi
    while :; do
        # A mark set while a write changes the files is the write's own.
        "$GUI_FLOCK" 8
        if gui_writer_active drop; then
            "$GUI_FLOCK" -u 8
            gui_result=superseded
            return 0
        fi
        gui_marked=0
        if qt5_failed_now; then
            gui_marked=1
        fi
        "$GUI_FLOCK" -u 8
        if [ -z "$gui_had_mark" ]; then
            gui_had_mark="$gui_marked"
        elif [ "$gui_had_mark" = "0" ] && [ "$gui_marked" = "1" ]; then
            gui_result=overlay_failed
            return 0
        fi
        sleep 1
        gui_waited=$((gui_waited + 1))
        gui_running="$(gui_pids BtClass)"
        if [ -z "$gui_running" ]; then
            gui_alive_at=
            if [ -z "$(gui_pids "$GUI_WRAPPER_NAME")" ]; then
                gui_result=failed
                return 0
            fi
        elif [ "$gui_running" != "$gui_seen_pid" ]; then
            # Another program than the one seen before: only its own writes count.
            if [ -n "$gui_seen_pid" ]; then
                gui_stamp="$GUI_RUN_DIR/seen"
                : > "$gui_stamp"
            fi
            gui_seen_pid="$gui_running"
            gui_alive_at=
        fi
        if [ -n "$gui_running" ] && [ -z "$gui_alive_at" ] && [ "$QT5_ALIVE_FILE" -nt "$gui_stamp" ]; then
            gui_alive_at="$gui_waited"
        fi
        if [ -n "$gui_alive_at" ] && [ $((gui_waited - gui_alive_at)) -ge "$QT5_STABLE_SECONDS" ]; then
            gui_result=ready
            return 0
        fi
        if [ -z "$gui_alive_at" ] && [ "$gui_waited" -ge "$QT5_START_SECONDS" ]; then
            gui_result=failed
            return 0
        fi
    done
}

# Start, with the mark dropped or set first, unless a write changes the
# activation files: nothing starts with half of them (returns 2).
gui_start_unless_writing() {
    "$GUI_FLOCK" 8
    if gui_writer_active drop; then
        "$GUI_FLOCK" -u 8
        return 2
    fi
    case "${2:-}" in
        drop_mark) rm -f "$QT5_RCC.failed" ;;
        mark) qt5_mark_failed 2>/dev/null || true ;;
    esac
    gui_start "$1" || true
    "$GUI_FLOCK" -u 8
}

# 0: a display runs, 1: none could be started, 2: a write changes the
# activation files; its own request restarts the display afterwards.
gui_cycle() {
    gui_phase stop
    gui_stop || return 1
    gui_settle
    if [ -n "$(gui_pids BtClass)" ]; then
        return 0
    fi
    gui_start_unless_writing "$GUI_WRAPPER" || return 2
    gui_verify
    if [ "$gui_result" = "overlay_failed" ] && [ "$1" = "retry" ]; then
        gui_phase stop
        gui_stop || return 1
        gui_settle
        gui_start_unless_writing "$GUI_WRAPPER" drop_mark || return 2
        gui_verify
    fi
    if [ "$gui_result" = "overlay_failed" ]; then
        gui_verify again
    fi
    if [ "$gui_result" = "failed" ] && grep -q 'c300x-qrc-overlay' "$GUI_WRAPPER" 2>/dev/null \
        && qt5_original_wrapper_valid "$QT5_WRAPPER_BACKUP"; then
        gui_phase stop
        gui_stop || return 1
        gui_settle
        gui_start_unless_writing "$QT5_WRAPPER_BACKUP" mark || return 2
        gui_verify
    fi
    [ "$gui_result" = "superseded" ] && return 2
    [ "$gui_result" = "ready" ]
}

gui_worker() {
    set +e
    mkdir -p "$GUI_RUN_DIR/requests" "$GUI_RUN_DIR/serving" "$GUI_RUN_DIR/done"
    exec 9>>"$GUI_RUN_DIR/lock" 8>>"$GUI_RUN_DIR/activation"
    "$GUI_FLOCK" -n 9 || exit 0
    # Requests of a worker that died are served again.
    for gui_request in "$GUI_RUN_DIR"/serving/*; do
        [ -f "$gui_request" ] && mv -f "$gui_request" "$GUI_RUN_DIR/requests/"
    done
    while :; do
        # A write in progress files its own request once its files are in place.
        while :; do
            "$GUI_FLOCK" 8
            gui_writer_active drop
            gui_writer_busy=$?
            "$GUI_FLOCK" -u 8
            [ "$gui_writer_busy" = "0" ] || break
            gui_phase wait
            sleep 1
        done
        gui_mode=
        for gui_request in "$GUI_RUN_DIR"/requests/*; do
            case "$gui_request" in
                *.tmp) continue ;;
            esac
            [ -f "$gui_request" ] || continue
            if [ "$(cat "$gui_request")" = "retry" ]; then
                gui_mode=retry
            elif [ -z "$gui_mode" ]; then
                gui_mode=keep
            fi
            mv -f "$gui_request" "$GUI_RUN_DIR/serving/"
        done
        if [ -z "$gui_mode" ]; then
            gui_phase idle
            # A request filed while the lock was still held is served too:
            # its requester saw a worker and started none.
            "$GUI_FLOCK" -u 9
            gui_requests_waiting && "$GUI_FLOCK" -n 9 && continue
            exit 0
        fi
        gui_answer=0
        gui_cycle "$gui_mode" || gui_answer=$?
        if [ "$gui_answer" = "2" ]; then
            # Served together with the write's request once it is done.
            for gui_request in "$GUI_RUN_DIR"/serving/*; do
                [ -f "$gui_request" ] && mv -f "$gui_request" "$GUI_RUN_DIR/requests/"
            done
            continue
        fi
        for gui_request in "$GUI_RUN_DIR"/serving/*; do
            [ -f "$gui_request" ] || continue
            gui_request="${gui_request##*/}"
            # Only for a requester still waiting; whole or not at all, as it
            # reads the answer as soon as it appears.
            if kill -0 "${gui_request%%.*}" 2>/dev/null; then
                printf '%s\n' "$gui_answer" > "$GUI_RUN_DIR/done/$gui_request.tmp" \
                    && mv -f "$GUI_RUN_DIR/done/$gui_request.tmp" "$GUI_RUN_DIR/done/$gui_request"
            fi
            rm -f "$GUI_RUN_DIR/serving/$gui_request"
        done
        # Answers of requesters that stopped waiting are never read.
        for gui_request in "$GUI_RUN_DIR"/done/*; do
            [ -f "$gui_request" ] || continue
            gui_request="${gui_request##*/}"
            kill -0 "${gui_request%%.*}" 2>/dev/null || rm -f "$GUI_RUN_DIR/done/$gui_request"
        done
    done
}

# A write that changes the activation files notes its PID here while it does;
# the worker then neither starts the display nor reads the quarantine mark,
# which the write sets while files change and settles when it is done.
gui_writing_begin() {
    [ "$QT5_DISPLAY" = "1" ] || return 0
    mkdir -p "$GUI_RUN_DIR" 2>/dev/null || return 0
    if command -v "$GUI_FLOCK" >/dev/null 2>&1; then
        "$GUI_FLOCK" "$GUI_RUN_DIR/activation" sh -c 'printf "%s\n" "$1" > "$2"' sh "$$" "$GUI_RUN_DIR/writing" || true
    else
        printf '%s\n' "$$" > "$GUI_RUN_DIR/writing" 2>/dev/null || true
    fi
}

gui_writing_end() {
    [ "$QT5_DISPLAY" = "1" ] || return 0
    if [ "$(cat "$GUI_RUN_DIR/writing" 2>/dev/null || true)" = "$$" ]; then
        rm -f "$GUI_RUN_DIR/writing"
    fi
    return 0
}

# A note whose PID is gone or is no longer this script (a killed writer, its
# PID reused) is no write; with "drop", called under the activation lock, the
# worker removes it. Only the worker asks, and it never writes: a note with its
# own PID is a killed writer's too.
gui_writer_active() {
    gui_writer="$(cat "$GUI_RUN_DIR/writing" 2>/dev/null || true)"
    [ -n "$gui_writer" ] || return 1
    if [ "$gui_writer" != "$$" ] && transaction_owner_running "$gui_writer"; then
        return 0
    fi
    if [ "${1:-}" = "drop" ]; then
        rm -f "$GUI_RUN_DIR/writing"
    fi
    return 1
}

gui_requests_waiting() {
    for gui_waiting in "$GUI_RUN_DIR"/requests/* "$GUI_RUN_DIR"/serving/*; do
        case "$gui_waiting" in
            *.tmp) continue ;;
        esac
        [ -f "$gui_waiting" ] && return 0
    done
    return 1
}

gui_spawn_worker() {
    if "$GUI_FLOCK" -n "$GUI_RUN_DIR/lock" true 2>/dev/null; then
        gui_session=
        if command -v setsid >/dev/null 2>&1; then
            gui_session=setsid
        fi
        (
            exec 9>&-
            $gui_session $GUI_SHELL "$0" gui-worker </dev/null >/dev/null 2>&1 &
        )
    fi
}

# 0: a display program runs, 1: none could be started, 2: still restarting
# when the wait ended (not a failure; the worker finishes the restart).
gui_restart() {
    # Without the lock no worker can run: fail now instead of waiting for nobody.
    if ! command -v "$GUI_FLOCK" >/dev/null 2>&1; then
        printf 'The display restart needs flock, which is missing on this station\n' >&2
        return 1
    fi
    mkdir -p "$GUI_RUN_DIR/requests" "$GUI_RUN_DIR/serving" "$GUI_RUN_DIR/done" || return 1
    gui_id="${GUI_PENDING_ID:-}"
    # A finishing step repeated after a signal waits for the request it filed.
    if [ "${FINISH_STEP_REPEAT:-0}" != "1" ] || [ -z "$gui_id" ] \
        || { [ ! -f "$GUI_RUN_DIR/requests/$gui_id" ] && [ ! -f "$GUI_RUN_DIR/serving/$gui_id" ] \
            && [ ! -f "$GUI_RUN_DIR/done/$gui_id" ]; }; then
        GUI_REQUESTS=$((GUI_REQUESTS + 1))
        gui_id="$$.$GUI_REQUESTS"
        rm -f "$GUI_RUN_DIR/done/$gui_id"
        printf '%s\n' "$1" > "$GUI_RUN_DIR/requests/$gui_id.tmp" || return 1
        mv -f "$GUI_RUN_DIR/requests/$gui_id.tmp" "$GUI_RUN_DIR/requests/$gui_id" || return 1
    fi
    GUI_PENDING_ID="$gui_id"
    gui_until=$((SCRIPT_STARTED + GUI_BUDGET_SECONDS))
    while :; do
        # At most 5 s after the first signal, also across a repeated step.
        if [ "${FINISH_SIGNALLED:-0}" = "1" ] && [ -z "${GUI_SIGNAL_UNTIL:-}" ]; then
            GUI_SIGNAL_UNTIL=$(($(date +%s) + 5))
        fi
        if [ -n "${GUI_SIGNAL_UNTIL:-}" ] && [ "$GUI_SIGNAL_UNTIL" -lt "$gui_until" ]; then
            gui_until="$GUI_SIGNAL_UNTIL"
        fi
        gui_answer="$(cat "$GUI_RUN_DIR/done/$gui_id" 2>/dev/null || true)"
        if [ -n "$gui_answer" ]; then
            rm -f "$GUI_RUN_DIR/done/$gui_id"
            GUI_PENDING_ID=
            [ "$gui_answer" = "0" ] && return 0
            return 1
        fi
        gui_spawn_worker
        [ "$(date +%s)" -lt "$gui_until" ] || return 2
        sleep 1
    done
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

# Firmware 1.7.19 and 2.0.2: the restart of release 2.9.1, unchanged.
reload_gui_qt4() {
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

reload_gui() {
    if [ "$RELOAD_GUI" != "1" ]; then
        return 0
    fi
    if [ "$QT5_DISPLAY" != "1" ]; then
        reload_gui_qt4
        return
    fi
    reload_mode=keep
    if qt5_retry_action; then
        reload_mode=retry
    fi
    reload_rc=0
    gui_restart "$reload_mode" || reload_rc=$?
    if [ "$reload_rc" = "1" ]; then
        printf 'No display program could be started\n' >&2
        return 1
    fi
}

# The agent's SIGTERM at the job deadline can fall between the stop and the
# start of the GUI. The restart is repeated once, so the display is not left off.
# On the Qt 5 display the restart worker, in a session of its own, stops and
# starts the display; it serves the filed request without this script, and a
# repeat here would file a second restart.
abort_reload() {
    trap : HUP INT TERM
    if [ "$QT5_DISPLAY" != "1" ]; then
        reload_gui || true
    fi
    exit 131
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
    [ "$mark_gui" = "$GUI_DIR" ] || return 1
    [ "$mark_pid" = "$$" ] || ! transaction_owner_running "$mark_pid"
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
    qt5_transaction_restore "$1" || rollback_ok=0
    [ "$rollback_ok" = "1" ]
}

remove_transaction() {
    rm -f "$1/.c300x-reload" "$1/.c300x-files" "$1/.c300x-files.tmp" || return 1
    rm -rf "$1/.qt5" || return 1
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
        case "$legacy_rel" in
            .qt5/*) continue ;;
        esac
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
    qt5_legacy_unchanged "$1" || return 1
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

recover_pass() {
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
        qt5_drop_recovery_copies
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

# The agent's SIGTERM at the job deadline ends the command it meets as well.
# Every step can be repeated, so one more pass finishes the recovery, the GUI
# restart and the read-only remount included. The signal stays caught, not
# ignored: a GUI started here must not inherit an ignored SIGTERM.
abort_recovery() {
    trap : HUP INT TERM
    # Qt 5: the repeat waits for the display restart the first pass filed
    # (at most 5 s, the worker finishes it), instead of filing a second one.
    if [ "$QT5_DISPLAY" = "1" ]; then
        FINISH_SIGNALLED=1
        FINISH_STEP_REPEAT=1
    fi
    recover_pass || true
    exit 131
}

recover_transactions() {
    trap abort_recovery HUP INT TERM
    recover_rc=0
    recover_pass || recover_rc=$?
    trap - HUP INT TERM
    return "$recover_rc"
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
        FINISH_STEP_REPEAT=1
        "$@" || finish_step_rc=$?
        FINISH_STEP_REPEAT=0
    fi
    return "$finish_step_rc"
}

finish_write_action() {
    write_rc=$?
    trap - EXIT
    # A signal that ended the write bounds the restart wait like a later one.
    FINISH_SIGNALLED="${WRITE_SIGNALLED:-0}"
    trap finish_signal HUP INT TERM
    # A publish cut short leaves its note; the rollback below takes a new one.
    gui_writing_end
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
    cleanup_staging
    if [ "$recovery_ok" = "1" ] && [ "$write_root_ro" = "1" ] && [ "${WRITE_TRANSACTION_COMMITTED:-0}" != "1" ]; then
        exit 130
    fi
    exit 131
}

abort_write_action() {
    WRITE_SIGNALLED=1
    finish_write_action || true
    exit_write_signal
}

run_write_action() {
    if [ "$QT5_DISPLAY" = "1" ]; then
        for qt5_artifact in rcc wrapper library original failed; do
            qt5_artifact_path "$qt5_artifact"
            qt5_require_regular
        done
        if ! qt5_original_wrapper_valid "$GUI_WRAPPER" \
            && ! qt5_original_wrapper_valid "$QT5_WRAPPER_BACKUP"; then
            printf 'Unsupported display start script or original backup; activation unchanged\n' >&2
            return 1
        fi
    fi
    WRITE_TRANSACTION=
    WRITE_TRANSACTION_READY=0
    WRITE_TRANSACTION_COMMITTED=0
    WRITE_RELOAD_ATTEMPTED=0
    REMOVE_EMPTY_JS=0
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
    qt5_transaction_save
    sync
    mv -f "$WRITE_TRANSACTION/.c300x-files.tmp" "$WRITE_TRANSACTION/.c300x-files"
    sync
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
            print "        }, page, function() { return page.visible && generation === page.buttonReadGeneration })"
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
        function print_home_assistant_button(name, flag, icon, size, description, target) {
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
            print "                style: Item {"
            print "                    width: bg.width"
            print "                    height: bg.height + label.height"
            print "                    Image {"
            print "                        id: bg"
            print "                        source: control.pressed ? \"images/function_btn_p.svg\" : \"images/function_btn.svg\""
            print "                    }"
            print "                    Image {"
            print "                        anchors.centerIn: bg"
            print "                        source: control.pressed ? \"images/" icon "_p.svg\" : \"images/" icon ".svg\""
            print "                        " size
            print "                    }"
            print "                    UbuntuLightText {"
            print "                        id: label"
            print "                        anchors.top: bg.bottom"
            print "                        anchors.topMargin: 2"
            print "                        anchors.horizontalCenter: bg.horizontalCenter"
            print "                        width: bg.width + foobar.spacing"
            print "                        horizontalAlignment: Text.AlignHCenter"
            print "                        elide: Text.ElideRight"
            print "                        color: \"white\""
            print "                        font.pixelSize: 18"
            print "                        text: " description
            print "                    }"
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
            print_home_assistant_button("alarmButton", "alarmButtonVisible", "keylock_icon-small", "sourceSize.width: 46", "trsl.language === \"de\" ? \"Alarmanlage\" : (trsl.language === \"it\" ? \"Allarme\" : (trsl.language === \"fr\" ? \"Alarme\" : \"Alarm\"))", "alarmPage")
            print ""
            print_home_assistant_button("haButton", "haButtonVisible", "call/icon_call-home", "sourceSize.height: 41", "\"Home Assistant\"", "haPage")
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
            sub(/message: qsTr\("Calls forwarded to the smartphones in the home"\) \+ trsl.empty/, "message: (trsl.language === \"de\" ? \"Anrufe an Home Assistant weitergeleitet\" : (trsl.language === \"it\" ? \"Chiamate inoltrate a Home Assistant\" : (trsl.language === \"fr\" ? \"Appels renvoyés vers Home Assistant\" : \"Calls forwarded to Home Assistant\"))) + trsl.empty")
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
            qt5_unsupported display_file_unsupported
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
            case "$qt5_result" in
                *'"display_program_unknown"'*) qt5_unsupported display_program_unknown ;;
                *'"display_resource_missing"'*) qt5_unsupported display_resource_missing ;;
            esac
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

qt5_unsupported() {
    mkdir -p "$QT5_ROOT"
    printf '%s\n' "$1" > "$QT5_UNSUPPORTED"
}

qt5_wrapper_supported() {
    if [ -f "$GUI_WRAPPER" ] && ! grep -q 'c300x-qrc-overlay' "$GUI_WRAPPER" \
        && ! qt5_original_wrapper_valid "$GUI_WRAPPER"; then
        printf 'Unsupported display start script: %s\n' "$GUI_WRAPPER" >&2
        qt5_unsupported display_wrapper_unknown
        return 1
    fi
}

qt5_prepare_or_report() {
    [ "$QT5_DISPLAY" = "1" ] || return 0
    rm -f "$QT5_UNSUPPORTED"
    if sh "$0" qt5-prepare >&2; then
        return 0
    fi
    [ -s "$QT5_UNSUPPORTED" ] || return 1
    json_status | sed 's/^{"ok":true/{"ok":false,"error":"display_unsupported"/'
    exit 0
}

qt5_boot_id() {
    cat "$QT5_BOOT_ID" 2>/dev/null || true
}

qt5_failed_now() {
    if [ ! -e "$QT5_RCC.failed" ]; then
        return 1
    fi
    if [ ! -f "$QT5_RCC.failed" ]; then
        return 0
    fi
    [ "$(cat "$QT5_RCC.failed" 2>/dev/null)" = "$(qt5_boot_id)" ]
}

qt5_mark_failed() {
    qt5_boot_id > "$QT5_RCC.failed"
}

qt5_retry_action() {
    case "$ACTION" in
        apply|core-apply|media-user-label-apply) return 0 ;;
    esac
    return 1
}

qt5_overlay_state() {
    if qt5_failed_now; then
        printf 'failed\n'
    elif [ -s "$QT5_RCC" ] && [ -s "$QT5_OVERLAY_LIB" ] && [ -x "$GUI_WRAPPER" ] \
        && [ -s "$QT5_WRAPPER_BACKUP" ] && grep -q 'c300x-qrc-overlay' "$GUI_WRAPPER" 2>/dev/null; then
        printf 'active\n'
    elif [ -e "$QT5_RCC" ] || [ -e "$QT5_OVERLAY_LIB" ] \
        || { [ ! -f "$GUI_WRAPPER" ] && [ -f "$QT5_WRAPPER_BACKUP" ]; } \
        || grep -q 'c300x-qrc-overlay' "$GUI_WRAPPER" 2>/dev/null; then
        printf 'incomplete\n'
    else
        printf 'off\n'
    fi
}

# The vendor start script with the overlay ahead of the plain start. A display
# that ends with an error within a minute of starting with the overlay marks it
# failed for this boot and starts as shipped.
# Its error output, where Qt reports QML errors, goes to a log of at most 64 KB.
qt5_wrapper_text() {
    awk -v lib="$QT5_OVERLAY_LIB" -v rcc="$QT5_RCC" -v errlog="$QT5_LOG" -v bootid="$QT5_BOOT_ID" '
        $0 == "./bin/gui/BtClass &" && !done {
            print "# c300x-qrc-overlay: display pages of the Home Assistant integration"
            print "c300x_boot=$(cat \047" bootid "\047 2>/dev/null)"
            print "if [ -f \047" lib "\047 ] && [ -f \047" rcc "\047 ] && { [ ! -e \047" rcc ".failed\047 ] || [ \"$(cat \047" rcc ".failed\047 2>/dev/null)\" != \"$c300x_boot\" ]; }; then"
            print "    c300x_start=$(date +%s)"
            print "    rm -f \047" errlog ".rc\047"
            print "    { { LD_PRELOAD=\047" lib "\047 C300X_QRC_OVERLAY=\047" rcc "\047 QML_DISABLE_DISK_CACHE=1 C300X_QRC_FAILED_ID=\"$c300x_boot\" ./bin/gui/BtClass 2>&1 1>&3 3>&-; echo $? > \047" errlog ".rc\047; } | { head -c 65536 > \047" errlog "\047; cat > /dev/null; }; } 3>&1 &"
            print "    wait $!"
            print "    c300x_rc=$(cat \047" errlog ".rc\047 2>/dev/null || echo 0)"
            print "    case $c300x_rc in 0|137|138|140|143) exit $c300x_rc ;; esac"
            print "    [ $(($(date +%s) - c300x_start)) -lt 60 ] || exit $c300x_rc"
            print "    printf \047%s\\n\047 \"$c300x_boot\" > \047" rcc ".failed\047"
            print "fi"
            done = 1
        }
        { print }
        END { if (!done) exit 1 }
    ' "${1:-$QT5_WRAPPER_BACKUP}"
}

# The start script without our block, of this or any earlier version: the
# lines from our comment to the first "fi" right before the vendor's start.
qt5_wrapper_strip() {
    awk '
        skip && $0 == "fi" { skip = 0; ended = 1; next }
        skip { next }
        !seen && $0 == "# c300x-qrc-overlay: display pages of the Home Assistant integration" {
            seen = 1; skip = 1; next
        }
        ended == 1 { ended = 2; if ($0 != "./bin/gui/BtClass &") bad = 1 }
        { print }
        END { if (!seen || ended != 2 || bad) exit 1 }
    ' "$1"
}

qt5_original_wrapper_valid() {
    [ -x "$1" ] || return 1
    qt5_wrapper_result="$("$AGENT_BIN" --display-qt5 wrapper-check "$1" 2>/dev/null)" || return 1
    case "$qt5_wrapper_result" in
        *'"ok":true'*) return 0 ;;
        *) return 1 ;;
    esac
}

qt5_wrapper_install() {
    if [ -f "$GUI_WRAPPER" ] && ! grep -q 'c300x-qrc-overlay' "$GUI_WRAPPER"; then
        if ! qt5_original_wrapper_valid "$GUI_WRAPPER"; then
            printf 'Unsupported display start script: %s\n' "$GUI_WRAPPER" >&2
            return 1
        fi
        mkdir -p "$(dirname "$QT5_WRAPPER_BACKUP")"
        cp -p "$GUI_WRAPPER" "$QT5_WRAPPER_BACKUP.tmp"
        mv -f "$QT5_WRAPPER_BACKUP.tmp" "$QT5_WRAPPER_BACKUP"
    fi
    if ! qt5_original_wrapper_valid "$QT5_WRAPPER_BACKUP" || ! qt5_wrapper_text > "$GUI_WRAPPER.c300x.tmp"; then
        rm -f "$GUI_WRAPPER.c300x.tmp"
        printf 'Unsupported display start script: %s\n' "$GUI_WRAPPER" >&2
        return 1
    fi
    if cmp -s "$GUI_WRAPPER.c300x.tmp" "$GUI_WRAPPER"; then
        rm -f "$GUI_WRAPPER.c300x.tmp"
        [ -x "$GUI_WRAPPER" ] || chmod 755 "$GUI_WRAPPER"
        return 0
    fi
    chmod 755 "$GUI_WRAPPER.c300x.tmp"
    mv -f "$GUI_WRAPPER.c300x.tmp" "$GUI_WRAPPER"
}

qt5_wrapper_restore() {
    if qt5_original_wrapper_valid "$GUI_WRAPPER"; then
        return 0
    fi
    if ! qt5_original_wrapper_valid "$QT5_WRAPPER_BACKUP"; then
        printf 'No verified original of the display start script: %s\n' "$QT5_WRAPPER_BACKUP" >&2
        return 1
    fi
    if [ -e "$GUI_WRAPPER" ]; then
        if ! qt5_wrapper_strip "$GUI_WRAPPER" > "$GUI_WRAPPER.c300x.tmp" \
            || ! cmp -s "$GUI_WRAPPER.c300x.tmp" "$QT5_WRAPPER_BACKUP"; then
            rm -f "$GUI_WRAPPER.c300x.tmp"
            printf 'Display start script is not the one installed here, left unchanged: %s\n' "$GUI_WRAPPER" >&2
            qt5_unsupported display_wrapper_unknown
            return 0
        fi
    fi
    cp -p "$QT5_WRAPPER_BACKUP" "$GUI_WRAPPER.c300x.tmp"
    qt5_original_wrapper_valid "$GUI_WRAPPER.c300x.tmp"
    mv -f "$GUI_WRAPPER.c300x.tmp" "$GUI_WRAPPER"
    qt5_original_wrapper_valid "$GUI_WRAPPER"
}

qt5_artifact_path() {
    case "$1" in
        rcc) qt5_target="$QT5_RCC" ;;
        wrapper) qt5_target="$GUI_WRAPPER" ;;
        library) qt5_target="$QT5_OVERLAY_LIB" ;;
        original) qt5_target="$QT5_WRAPPER_BACKUP" ;;
        failed) qt5_target="$QT5_RCC.failed" ;;
    esac
}

qt5_transaction_save() {
    [ "$QT5_DISPLAY" = "1" ] || return 0
    mkdir "$WRITE_TRANSACTION/.qt5"
    for qt5_artifact in rcc wrapper library original failed; do
        qt5_artifact_path "$qt5_artifact"
        qt5_require_regular
        if [ -f "$qt5_target" ]; then
            cp -p "$qt5_target" "$WRITE_TRANSACTION/.qt5/$qt5_artifact"
        fi
    done
}

qt5_require_regular() {
    if [ -L "$qt5_target" ] || { [ -e "$qt5_target" ] && [ ! -f "$qt5_target" ]; }; then
        printf 'Unsupported display activation file: %s\n' "$qt5_target" >&2
        return 1
    fi
}

# A recovery copy beside an activation file whose writer was killed (SIGKILL
# after the job's grace period) is never used again: the rollback makes its own.
qt5_drop_recovery_copies() {
    [ "$QT5_DISPLAY" = "1" ] || return 0
    for qt5_artifact in rcc wrapper library original failed; do
        qt5_artifact_path "$qt5_artifact"
        for qt5_copy in "$qt5_target".c300x-recovery.*; do
            [ -f "$qt5_copy" ] && [ ! -L "$qt5_copy" ] || continue
            transaction_owner_running "${qt5_copy##*.}" && continue
            rm -f "$qt5_copy" || true
        done
    done
}

qt5_restore_artifact() {
    qt5_artifact_path "$2"
    qt5_saved="$1/.qt5/$2"
    if [ -f "$qt5_saved" ]; then
        # The wrapper may live on another filesystem. Keep the recovery copy
        # until every artifact is restored; rename only beside the destination.
        # A step cut off by a signal runs again in this process: drop its copy.
        qt5_recovery="$qt5_target.c300x-recovery.$$"
        if ! rm -f "$qt5_recovery" \
            || ! (umask 077; set -C; : > "$qt5_recovery") \
            || ! cp -p "$qt5_saved" "$qt5_recovery" \
            || ! mv -f "$qt5_recovery" "$qt5_target"; then
            return 1
        fi
    else
        rm -f "$qt5_target" || return 1
    fi
}

# Copies are kept until the transaction is removed, so a recovery cut off at
# any point can run again. Only a write that began to publish changed them.
qt5_transaction_restore() {
    [ -f "$1/.qt5/.published" ] || return 0
    gui_writing_begin
    qt5_restore_rc=0
    qt5_transaction_restore_files "$1" || qt5_restore_rc=$?
    gui_writing_end
    return "$qt5_restore_rc"
}

qt5_transaction_restore_files() {
    for qt5_artifact in rcc library wrapper; do
        qt5_artifact_path "$qt5_artifact"
        if [ -f "$1/.qt5/$qt5_artifact" ]; then
            cmp -s "$1/.qt5/$qt5_artifact" "$qt5_target" && continue
        elif [ ! -e "$qt5_target" ] && [ ! -L "$qt5_target" ]; then
            continue
        fi
        : > "$1/.c300x-reload" || return 1
    done
    # A restart during recovery must not load a mixture of old and new files.
    qt5_mark_failed || return 1
    qt5_restore_ok=1
    for qt5_artifact in rcc library original wrapper; do
        qt5_restore_artifact "$1" "$qt5_artifact" || qt5_restore_ok=0
    done
    [ "$qt5_restore_ok" = "1" ] && qt5_restore_artifact "$1" failed
}

# A write of agent 2.9.0 or older kept no publish mark: its activation copies
# count only while every one equals the file in place.
qt5_legacy_unchanged() {
    [ -d "$1/.qt5" ] || return 0
    for qt5_artifact in rcc library wrapper original; do
        qt5_artifact_path "$qt5_artifact"
        if [ -f "$1/.qt5/$qt5_artifact" ]; then
            cmp -s "$1/.qt5/$qt5_artifact" "$qt5_target" || return 1
        elif [ -e "$qt5_target" ] || [ -L "$qt5_target" ]; then
            return 1
        fi
    done
}

# Every file that differs from the firmware's, back in Qt 5 form, into the
# resource file. The deterministic candidate also repairs activation-only drift.
qt5_pack_resources() {
    # A stage of a script killed past its grace period stays on storage.
    for qt5_stage in "$QT5_ROOT"/rcc-stage.*; do
        [ -d "$qt5_stage" ] || continue
        [ "${qt5_stage##*.}" != "$$" ] && transaction_owner_running "${qt5_stage##*.}" && continue
        rm -rf "$qt5_stage"
    done
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
    if [ -z "$qt5_files" ]; then
        rm -rf "$qt5_stage"
        return
    fi
    qt5_result="$("$AGENT_BIN" --display-qt5 pack "$qt5_stage" "$1" $qt5_files 2>/dev/null || true)"
    rm -rf "$qt5_stage"
    case "$qt5_result" in
        *'"ok":true'*) ;;
        *)
            printf 'Cannot write the display resource file: %s\n' "$qt5_result" >&2
            return 1
            ;;
    esac
}

qt5_write_overlay() {
    qt5_result="$("$AGENT_BIN" --display-qt5 overlay "$1" 2>/dev/null || true)"
    case "$qt5_result" in
        *'"ok":true'*) ;;
        *)
            printf 'Cannot write the display preload library: %s\n' "$qt5_result" >&2
            return 1
            ;;
    esac
}

qt5_check_activation() {
    QT5_ACTIVATION_CHANGED=0
    trap cleanup_staging EXIT
    mkdir -p "$STAGING_DIR"
    for qt5_artifact in rcc wrapper library original failed; do
        qt5_artifact_path "$qt5_artifact"
        qt5_require_regular
    done
    qt5_pack_resources "$STAGING_DIR/.qt5-rcc"
    if qt5_retry_action && qt5_failed_now; then
        QT5_ACTIVATION_CHANGED=1
    fi
    if [ -z "$qt5_files" ]; then
        if [ "$(qt5_overlay_state)" != "off" ]; then
            QT5_ACTIVATION_CHANGED=1
        fi
        return
    fi
    qt5_write_overlay "$STAGING_DIR/.qt5-library"
    qt5_wrapper_source="$QT5_WRAPPER_BACKUP"
    if [ -f "$GUI_WRAPPER" ] && ! grep -q 'c300x-qrc-overlay' "$GUI_WRAPPER"; then
        qt5_wrapper_source="$GUI_WRAPPER"
    fi
    if ! qt5_original_wrapper_valid "$qt5_wrapper_source" \
        || ! qt5_wrapper_text "$qt5_wrapper_source" > "$STAGING_DIR/.qt5-wrapper"; then
        printf 'No usable original display start script\n' >&2
        return 1
    fi
    if ! cmp -s "$STAGING_DIR/.qt5-rcc" "$QT5_RCC" \
        || ! cmp -s "$STAGING_DIR/.qt5-library" "$QT5_OVERLAY_LIB" \
        || ! cmp -s "$STAGING_DIR/.qt5-wrapper" "$GUI_WRAPPER" \
        || [ ! -x "$GUI_WRAPPER" ]; then
        QT5_ACTIVATION_CHANGED=1
    fi
}

qt5_publish() {
    [ "$QT5_DISPLAY" = "1" ] || return 0
    gui_writing_begin
    : > "$WRITE_TRANSACTION/.qt5/.published"
    sync
    qt5_mark_failed
    qt5_files=
    # Full removal must also work when the disposable vendor cache or packer
    # is damaged. The stock resources remain embedded in the vendor program.
    if [ "$ACTION" != "restore-all" ]; then
        qt5_pack_resources "$QT5_RCC"
    fi
    if [ -z "$qt5_files" ]; then
        rm -f "$QT5_RCC"
        qt5_wrapper_restore
        rm -f "$QT5_OVERLAY_LIB"
        rm -f "$QT5_RCC.failed"
        gui_writing_end
        return
    fi
    qt5_write_overlay "$QT5_OVERLAY_LIB"
    qt5_wrapper_install
    if ! qt5_retry_action && [ -f "$WRITE_TRANSACTION/.qt5/failed" ] \
        && [ "$(cat "$WRITE_TRANSACTION/.qt5/failed")" = "$(qt5_boot_id)" ]; then
        cp -p "$WRITE_TRANSACTION/.qt5/failed" "$QT5_RCC.failed"
    else
        rm -f "$QT5_RCC.failed"
    fi
    gui_writing_end
}

cleanup_staging() {
    rm -rf "$STAGING_DIR"
    # The Qt 5 resource stage is on the station's storage, not in RAM.
    if [ "$QT5_DISPLAY" = "1" ]; then
        rm -rf "$QT5_ROOT/rcc-stage.$$"
    fi
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
    elif [ "$QT5_DISPLAY" = "1" ]; then
        qt5_check_activation
        if [ "$QT5_ACTIVATION_CHANGED" = "1" ]; then
            run_write_action "$@"
        fi
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
        qt5_prepare_or_report
        apply_patch_files
        run_touch_phase apply
        json_write_status
        ;;
    core-apply)
        qt5_prepare_or_report
        apply_core_patch_files
        json_write_status
        ;;
    media-user-label-apply)
        qt5_prepare_or_report
        apply_media_user_label_files
        json_write_status
        ;;
    restore)
        changed_count="$(restore_changed_count)"
        apply_generated_patch_if_changed "$changed_count" restore_patch_files
        cleanup_staging
        run_touch_phase restore
        json_write_status
        ;;
    core-restore)
        changed_count="$(restore_core_changed_count)"
        apply_generated_patch_if_changed "$changed_count" restore_core_patch_files
        cleanup_staging
        json_write_status
        ;;
    media-user-label-restore)
        changed_count="$(restore_media_user_label_changed_count)"
        apply_generated_patch_if_changed "$changed_count" restore_media_user_label_files
        cleanup_staging
        json_write_status
        ;;
    restore-all)
        changed_count="$(restore_all_changed_count)"
        if [ "$changed_count" -gt 0 ] || { [ "$QT5_DISPLAY" = "1" ] \
            && { [ "$(qt5_overlay_state)" != "off" ] || [ -e "$QT5_RCC.failed" ]; }; }; then
            run_write_action restore_all_patch_files
        fi
        run_touch_phase restore
        json_write_status
        ;;
    reload)
        trap abort_reload HUP INT TERM
        reload_gui
        trap - HUP INT TERM
        json_status
        ;;
    gui-worker)
        gui_worker
        ;;
    qt5-import)
        qt5_import "${2:?}"
        json_status
        ;;
    qt5-prepare)
        qt5_prepare
        qt5_wrapper_supported
        ;;
    *)
        printf '{"ok":false,"available":false,"state":"invalid_action"}\n'
        exit 2
        ;;
esac
