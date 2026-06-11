#!/bin/sh
set -eu

ACTION="${1:-status}"
GUI_DIR="${C300X_QML_GUI_DIR:-/home/bticino/bin/gui/skins/default}"
SOURCE_DIR="${C300X_QML_SOURCE_DIR:-/home/bticino/cfg/extra/c300x-native-agent/qml}"
BACKUP_DIR="${C300X_QML_BACKUP_DIR:-/home/bticino/cfg/extra/c300x-device-file-backups/original/gui/skins/default}"
NO_REMOUNT="${C300X_QML_NO_REMOUNT:-0}"
RELOAD_GUI="${C300X_QML_RELOAD_GUI:-1}"
GUI_ROOT="${C300X_QML_GUI_ROOT:-/home/bticino}"
GUI_WRAPPER="${C300X_QML_GUI_WRAPPER:-/home/bticino/bin/BtClass_qws}"
GUI_RELOAD_DELAY_SECONDS="${C300X_QML_GUI_RELOAD_DELAY_SECONDS:-2}"
STAGING_DIR="${C300X_QML_STAGING_DIR:-${TMPDIR:-/tmp}/c300x-qml-patch.$$}"
CORE_PATCH_FILES="EventManager.qml"
INHOUSE_PATCH_FILES="Components/Settings/CallBlockPopup.qml"
FEATURE_PATCH_FILES="MainApp.qml HomePage.qml MemoPage.qml Alarm.qml HomeAssistant.qml js/c300x_ha.js js/c300x_i18n.js js/c300x_memos.js"
PATCH_FILES="$FEATURE_PATCH_FILES $CORE_PATCH_FILES"
OBSOLETE_GUI_FILES="C300XText.qml images/c300x_alarm_icon.svg images/c300x_alarm_icon_p.svg images/c300x_home_assistant_icon.svg images/c300x_home_assistant_icon_p.svg"

json_status() {
    changed_files="${1:-}"
    state=original
    patched=false
    core_state=original
    core_patched=false
    inhouse_state=original
    inhouse_patched=false
    backup_available=false
    core_backup_available=false
    inhouse_backup_available=false
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
    if inhouse_patch_present; then
        inhouse_state=patched
        inhouse_patched=true
    elif inhouse_partial_patch_present; then
        inhouse_state=partial
        inhouse_patched=null
    fi
    if [ -f "$BACKUP_DIR/MainApp.qml" ]; then
        backup_available=true
    fi
    if [ -f "$BACKUP_DIR/EventManager.qml" ]; then
        core_backup_available=true
    fi
    if [ -f "$BACKUP_DIR/Components/Settings/CallBlockPopup.qml" ]; then
        inhouse_backup_available=true
    fi
    if command -v pidof >/dev/null 2>&1 && pidof BtClass >/dev/null 2>&1; then
        gui_running=true
    fi
    if [ -n "$changed_files" ]; then
        printf '{"ok":true,"available":true,"state":"%s","patched":%s,"core_state":"%s","core_patched":%s,"inhouse_state":"%s","inhouse_patched":%s,"backup_available":%s,"core_backup_available":%s,"inhouse_backup_available":%s,"gui_running":%s,"changed_files":%s}\n' "$state" "$patched" "$core_state" "$core_patched" "$inhouse_state" "$inhouse_patched" "$backup_available" "$core_backup_available" "$inhouse_backup_available" "$gui_running" "$changed_files"
    else
        printf '{"ok":true,"available":true,"state":"%s","patched":%s,"core_state":"%s","core_patched":%s,"inhouse_state":"%s","inhouse_patched":%s,"backup_available":%s,"core_backup_available":%s,"inhouse_backup_available":%s,"gui_running":%s}\n' "$state" "$patched" "$core_state" "$core_patched" "$inhouse_state" "$inhouse_patched" "$backup_available" "$core_backup_available" "$inhouse_backup_available" "$gui_running"
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
        && file_contains "$GUI_DIR/HomePage.qml" 'id: homeAssistantButtonRow' \
        && file_contains "$GUI_DIR/HomePage.qml" 'MemoSync.syncHomeNotifications(page)' \
        && file_contains "$GUI_DIR/HomePage.qml" 'objectName: "alarmButton"' \
        && file_contains "$GUI_DIR/HomePage.qml" 'objectName: "haButton"' \
        && file_contains "$GUI_DIR/HomePage.qml" 'images/call/icon_call-home.svg' \
        && file_contains "$GUI_DIR/MemoPage.qml" 'MemoSync.syncMemoModel' \
        && file_contains "$GUI_DIR/Alarm.qml" 'headerLabel: uiText("alarm")' \
        && file_contains "$GUI_DIR/HomeAssistant.qml" 'Api.dashboard' \
        && file_contains "$GUI_DIR/js/c300x_ha.js" 'function homeButtons' \
        && file_contains "$GUI_DIR/js/c300x_i18n.js" 'function weather' \
        && file_contains "$GUI_DIR/js/c300x_memos.js" 'function unreadCountFromPath' \
        && file_contains "$GUI_DIR/js/c300x_memos.js" 'function syncMemoModel'
}

partial_patch_present() {
    file_contains "$GUI_DIR/MainApp.qml" 'sourceUrl: "Alarm.qml"' \
        || file_contains "$GUI_DIR/MainApp.qml" 'sourceUrl: "HomeAssistant.qml"' \
        || file_contains "$GUI_DIR/HomePage.qml" 'id: homeAssistantButtonRow' \
        || file_contains "$GUI_DIR/MemoPage.qml" 'MemoSync.syncMemoModel' \
        || [ -f "$GUI_DIR/Alarm.qml" ] \
        || [ -f "$GUI_DIR/HomeAssistant.qml" ] \
        || [ -f "$GUI_DIR/js/c300x_ha.js" ] \
        || [ -f "$GUI_DIR/js/c300x_i18n.js" ] \
        || [ -f "$GUI_DIR/js/c300x_memos.js" ]
}

core_patch_present() {
    file_contains "$GUI_DIR/EventManager.qml" 'function c300xNotifyMediaClosed()' \
        && file_contains "$GUI_DIR/EventManager.qml" '/ui/media-closed' \
        && core_call_end_hooks_present
}

core_partial_patch_present() {
    file_contains "$GUI_DIR/EventManager.qml" 'function c300xNotifyMediaClosed()' \
        || file_contains "$GUI_DIR/EventManager.qml" '/ui/media-closed' \
        || file_contains "$GUI_DIR/EventManager.qml" 'c300xNotifyMediaClosed()'
}

inhouse_patch_present() {
    file_contains "$GUI_DIR/Components/Settings/CallBlockPopup.qml" 'Forward calls to Home Assistant' \
        && file_contains "$GUI_DIR/Components/Settings/CallBlockPopup.qml" 'Calls forwarded to Home Assistant'
}

inhouse_partial_patch_present() {
    file_contains "$GUI_DIR/Components/Settings/CallBlockPopup.qml" 'Forward calls to Home Assistant' \
        || file_contains "$GUI_DIR/Components/Settings/CallBlockPopup.qml" 'Calls forwarded to Home Assistant'
}

core_call_end_hooks_present() {
    [ -f "$GUI_DIR/EventManager.qml" ] || return 1
    awk '
        $0 == "        onCallEnded: {" {
            count += 1
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
        (
            cd "$GUI_ROOT"
            /bin/sh "$GUI_WRAPPER" >/tmp/BtClass_qws.agent.log 2>&1 &
        )
    fi
    sleep "$GUI_RELOAD_DELAY_SECONDS"
    if ! command -v pidof >/dev/null 2>&1; then
        return 0
    fi
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
    remount_ro
    trap - EXIT HUP INT TERM
}

abort_write_action() {
    remount_ro
    trap - EXIT HUP INT TERM
    exit 130
}

run_write_action() {
    trap finish_write_action EXIT
    trap abort_write_action HUP INT TERM
    remount_rw
    "$@"
    finish_write_action
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
        EventManager.qml)
            if grep -F -q 'function c300xNotifyMediaClosed()' "$backup_src"; then
                printf 'Refusing to back up an already patched EventManager.qml\n' >&2
                return 1
            fi
            ;;
        MainApp.qml)
            if grep -F -q 'sourceUrl: "Alarm.qml"' "$backup_src" \
                || grep -F -q 'sourceUrl: "HomeAssistant.qml"' "$backup_src"; then
                printf 'Refusing to back up an already patched MainApp.qml\n' >&2
                return 1
            fi
            ;;
    esac
    mkdir -p "$(dirname "$backup_dest")"
    cp -p "$backup_src" "$backup_dest"
}

install_file() {
    install_rel="$1"
    backup_mode="${2:-original}"
    install_src="$SOURCE_DIR/$install_rel"
    install_dest="${PATCH_OUTPUT_DIR:-$GUI_DIR}/$install_rel"
    [ -f "$install_src" ]
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
    awk '
        function print_memo_sync_import() {
            if (!printed_memo_sync_import) {
                print "import \"js/c300x_memos.js\" as MemoSync"
                printed_memo_sync_import=1
            }
        }
        function print_home_notification_helpers() {
            print ""
            print "    property int externalUnreadMessages: -1"
            print "    property int externalUnreadMemos: -1"
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
            print "        if (event && (event.topic === \"memos\" || event.topic === \"answering_machine.messages\")) {"
            print "            refreshMessageNotifications()"
            print "        }"
            print "    }"
            print ""
            print "    function startMessageNotificationWatch() {"
            print "        refreshMessageNotifications()"
            print "        MemoSync.startEventWatch(handleMessageNotificationEvent)"
            print "    }"
            print ""
            print "    function stopMessageNotificationWatch() {"
            print "        MemoSync.stopEventWatch()"
            print "    }"
        }
        function print_home_assistant_flow_item() {
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
            next
        }
        $0 == "    function aboutToShow() {" {
            in_about_to_show=1
            print
            next
        }
        in_about_to_show && $0 == "    }" {
            print "        refreshMessageNotifications()"
            print
            in_about_to_show=0
            next
        }
        $0 == "                loader.item.setDate()" {
            print
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
    verify_generated_page \
        "$temp_file" \
        "HomePage.qml" \
        'import "js/c300x_memos.js" as MemoSync' \
        'function refreshMessageNotifications()' \
        'function startMessageNotificationWatch()' \
        'MemoSync.syncHomeNotifications(page)' \
        'id: homeAssistantButtonRow' \
        'objectName: "alarmButton"' \
        'objectName: "haButton"' \
        'images/call/icon_call-home.svg'
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
            sub(/message: qsTr\("Calls forwarded to the smartphones in the home"\) \+ trsl.empty/, "message: \"Calls forwarded to Home Assistant\" + trsl.empty")
            print
            message_patched=1
            next
        }
        /\/\/\{text: qsTr\("Forward calls to the smartphones in the home"\).*AnsweringMachine\.InHouseOnly/ {
            print "                    {text: \"Forward calls to Home Assistant\" + trsl.empty, action: AnsweringMachine.InHouseOnly},"
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
            print "        request.open(\"GET\", \"http://127.0.0.1:8092/ui/media-closed\", true)"
            print "        request.send()"
            print "    }"
            next
        }
        $0 == "        onCallEnded: {" {
            print
            print "            c300xNotifyMediaClosed()"
            next
        }
        { print }
    ' "$source_event_manager" > "$temp_file"
    verify_generated_page \
        "$temp_file" \
        "EventManager.qml" \
        'function c300xNotifyMediaClosed()' \
        'request.open("GET", "http://127.0.0.1:8092/ui/media-closed", true)' \
        'c300xNotifyMediaClosed()' \
        'onCallEnded:'
    mv "$temp_file" "$event_manager"
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
    mkdir -p "$STAGING_DIR"
    PATCH_OUTPUT_DIR="$STAGING_DIR"
    export PATCH_OUTPUT_DIR
    patch_event_manager
    unset PATCH_OUTPUT_DIR
}

generate_feature_patch_stage() {
    cleanup_staging
    mkdir -p "$STAGING_DIR/js"
    PATCH_OUTPUT_DIR="$STAGING_DIR"
    export PATCH_OUTPUT_DIR
    patch_home_page
    patch_memo_page
    copy_generated_file "Alarm.qml"
    copy_generated_file "HomeAssistant.qml"
    copy_generated_file "js/c300x_ha.js"
    copy_generated_file "js/c300x_i18n.js"
    copy_generated_file "js/c300x_memos.js"
    patch_main_app
    unset PATCH_OUTPUT_DIR
}

generate_full_patch_stage() {
    cleanup_staging
    mkdir -p "$STAGING_DIR/js"
    PATCH_OUTPUT_DIR="$STAGING_DIR"
    export PATCH_OUTPUT_DIR
    patch_event_manager
    patch_home_page
    patch_memo_page
    copy_generated_file "Alarm.qml"
    copy_generated_file "HomeAssistant.qml"
    copy_generated_file "js/c300x_ha.js"
    copy_generated_file "js/c300x_i18n.js"
    copy_generated_file "js/c300x_memos.js"
    patch_main_app
    unset PATCH_OUTPUT_DIR
}

generate_inhouse_patch_stage() {
    cleanup_staging
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

copy_changed_inhouse_patch_files() {
    copy_changed_patch_files $INHOUSE_PATCH_FILES
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
    printf '%s\n' "$changed_count"
}

apply_inhouse_patch_files() {
    generate_inhouse_patch_stage
    changed_count="$(apply_stage_changed_count $INHOUSE_PATCH_FILES)"
    apply_generated_patch_if_changed "$changed_count" copy_changed_inhouse_patch_files
    cleanup_staging
    printf '%s\n' "$changed_count"
}

apply_feature_patch_files() {
    generate_feature_patch_stage
    changed_count="$(apply_feature_stage_changed_count)"
    apply_generated_patch_if_changed "$changed_count" copy_changed_feature_patch_files
    cleanup_staging
    printf '%s\n' "$changed_count"
}

apply_patch_files() {
    generate_full_patch_stage
    changed_count="$(apply_full_stage_changed_count)"
    apply_generated_patch_if_changed "$changed_count" copy_changed_full_patch_files
    cleanup_staging
    printf '%s\n' "$changed_count"
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
    for rel in Alarm.qml HomeAssistant.qml js/c300x_ha.js js/c300x_i18n.js js/c300x_memos.js; do
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
        printf '1\n'
    else
        printf '0\n'
    fi
}

is_generated_patch_file() {
    case "$1" in
        Alarm.qml|HomeAssistant.qml|js/c300x_ha.js|js/c300x_i18n.js|js/c300x_memos.js)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

restore_feature_stock_file() {
    restore_rel="$1"
    if [ -e "$BACKUP_DIR/$restore_rel" ] || partial_patch_present; then
        restore_file "$restore_rel"
    fi
}

restore_patch_files() {
    restore_feature_stock_file "MainApp.qml"
    restore_feature_stock_file "HomePage.qml"
    restore_feature_stock_file "MemoPage.qml"
    restore_file "Alarm.qml"
    restore_file "HomeAssistant.qml"
    restore_file "js/c300x_ha.js"
    restore_file "js/c300x_i18n.js"
    restore_file "js/c300x_memos.js"
    remove_obsolete_gui_files
    rmdir "$GUI_DIR/js" >/dev/null 2>&1 || true
}

restore_inhouse_changed_count() {
    restore_original="$BACKUP_DIR/Components/Settings/CallBlockPopup.qml"
    restore_dest="$GUI_DIR/Components/Settings/CallBlockPopup.qml"
    if [ ! -e "$restore_original" ]; then
        if inhouse_partial_patch_present; then
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

restore_inhouse_patch_files() {
    restore_file "Components/Settings/CallBlockPopup.qml"
}

restore_core_patch_files() {
    restore_file "EventManager.qml"
}

restore_all_changed_count() {
    feature_changed_count="$(restore_changed_count)"
    core_changed_count="$(restore_core_changed_count)"
    printf '%s\n' "$((feature_changed_count + core_changed_count))"
}

restore_all_patch_files() {
    restore_patch_files
    restore_core_patch_files
}

case "$ACTION" in
    status)
        json_status
        ;;
    apply)
        changed_count="$(apply_patch_files)"
        if [ "$changed_count" -gt 0 ] && ! reload_gui; then
            json_reload_failed
            exit 0
        fi
        json_status "$changed_count"
        ;;
    core-apply)
        changed_count="$(apply_core_patch_files)"
        if [ "$changed_count" -gt 0 ] && ! reload_gui; then
            json_reload_failed
            exit 0
        fi
        json_status "$changed_count"
        ;;
    inhouse-apply)
        changed_count="$(apply_inhouse_patch_files)"
        if [ "$changed_count" -gt 0 ] && ! reload_gui; then
            json_reload_failed
            exit 0
        fi
        json_status "$changed_count"
        ;;
    restore)
        changed_count="$(restore_changed_count)"
        if [ "$changed_count" -gt 0 ]; then
            run_write_action restore_patch_files
        fi
        if [ "$changed_count" -gt 0 ] && ! reload_gui; then
            json_reload_failed
            exit 0
        fi
        json_status "$changed_count"
        ;;
    core-restore)
        changed_count="$(restore_core_changed_count)"
        if [ "$changed_count" -gt 0 ]; then
            run_write_action restore_core_patch_files
        fi
        if [ "$changed_count" -gt 0 ] && ! reload_gui; then
            json_reload_failed
            exit 0
        fi
        json_status "$changed_count"
        ;;
    inhouse-restore)
        changed_count="$(restore_inhouse_changed_count)"
        if [ "$changed_count" -gt 0 ]; then
            run_write_action restore_inhouse_patch_files
        fi
        if [ "$changed_count" -gt 0 ] && ! reload_gui; then
            json_reload_failed
            exit 0
        fi
        json_status "$changed_count"
        ;;
    restore-all)
        changed_count="$(restore_all_changed_count)"
        if [ "$changed_count" -gt 0 ]; then
            run_write_action restore_all_patch_files
        fi
        if [ "$changed_count" -gt 0 ] && ! reload_gui; then
            json_reload_failed
            exit 0
        fi
        json_status "$changed_count"
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
