from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "native_agent/scripts/qml_patch.sh"
SOURCE_DIR = ROOT / "device_qml"
# Synthetic reduced fixtures. These are not stock firmware QML files.
ORIGINAL_MAIN_APP = "\n".join(
    [
        "original main",
        "            homePage,",
        "            memoPage,",
        "            settingsPage,",
        "",
        "    PageLoader {",
        "        id: settingsPage",
        "        sourceUrl: \"Settings.qml\"",
        "    }",
        "",
    ]
)
ORIGINAL_HOME_PAGE = "\n".join(
    [
        "import QtQuick 1.1",
        "import Components 1.0",
        "import BtObjects 2.0",
        "import \"js/utils.js\" as Utils",
        "",
        "Page {",
        "    id: page",
        "",
        "    property bool smallDateTimePresent: homeLinksModel.count > 0 || buttonHolder.buttonCount() > 2",
        "    property variant networkManager: global.mNetworkManager",
        "    property string wifiIcon: \"\"",
        "",
        "    function aboutToShow() {",
        "        originalHomeSetup()",
        "    }",
        "",
        "    Connections {",
        "        target: page",
        "        onVisibleChanged: {",
        "            if (visible) {",
        "                var loader = smallDateTimePresent ? topDateTimeLoader : bigDateTimeLoader",
        "                loader.item.setTime()",
        "                loader.item.setDate()",
        "            } else {",
        "                originalHiddenHook()",
        "            }",
        "        }",
        "    }",
        "",
        "    Item {",
        "        id: buttonHolder",
        "",
        "        function buttonCount() {",
        "            return answerButton.isVisible()",
        "                    + cameraButton.isVisible()",
        "                    + intercomButton.isVisible()",
        "                    + activationsButton.isVisible()",
        "                    + 2",
        "        }",
        "",
        "        Flow {",
        "            id: foobar",
        "            height: buttonHolder.buttonCount() > 4 ? (buttonPrototype.height + spacing) * 2 : buttonPrototype.height",
        "            anchors.horizontalCenterOffset: page.smallDateTimePresent ? 0 : (parent.width / 2 - width / 2) - page.width / 100 * 2 // 16",
        "",
        "            BasicButton {",
        "                id: answerButton",
        "                function isVisible() { return true }",
        "                style: HomePageButtonStyle {",
        "                    notificationsCount: answeringModel.obj.unreadMessages",
        "                }",
        "            }",
        "",
        "            BasicButton { id: intercomButton; function isVisible() { return true } }",
        "            BasicButton { id: cameraButton; function isVisible() { return true } }",
        "            BasicButton { id: activationsButton; function isVisible() { return true } }",
        "",
        "            BasicButton {",
                "                objectName: \"memoButton\"",
                "                style: HomePageButtonStyle {",
                "                    notificationsCount: answeringModel.obj.unreadMemos",
                "                }",
        "            }",
        "",
        "            Item {",
        "                id: verticalSpacingForSettingsButton",
        "                visible: buttonHolder.buttonCount() === 5",
        "            }",
        "",
        "            BasicButton {",
        "                objectName: \"settingsButton\"",
        "                onTouched: tabView.activateTab(settingsPage)",
        "            }",
        "        }",
        "    }",
        "",
        "    Loader { id: favoritesLoader }",
        "}",
        "",
    ]
)
ORIGINAL_MEMO_PAGE = "\n".join(
    [
        "import QtQuick 1.1",
        "import BtObjects 2.0",
        "import Components 1.0",
        "import \"js/audiorecord.js\" as Utils",
        "",
        "GridPage {",
        "    id: page",
        "",
        "    headerLabel: qsTr(\"Memo\") + trsl.empty",
        "    onBackClicked: tabView.activateTab(homePage)",
        "    onObjectClicked: {",
        "        originalMemoOpen()",
        "    }",
        "",
        "    topMargin: 86",
        "    model: ObjectModel {",
        "        source: answering.obj.memos",
        "    }",
        "}",
        "",
    ]
)
ORIGINAL_CALL_BLOCK_POPUP = "\n".join(
    [
        "import QtQuick 1.1",
        "import BtObjects 2.0",
        "",
        "Item {",
        "    id: root",
        "    property variant answeringMachine",
        "",
        "    QtObject {",
        "        id: privateProps",
        "        property variant modes: [",
        "            {icon: \"../../images/call/icon_call-ok.svg\", message: qsTr(\"Calls forwarded to all the smartphones\") + trsl.empty},",
        "            {icon: \"../../images/call/icon_call-home.svg\", message: qsTr(\"Calls forwarded to the smartphones in the home\") + trsl.empty},",
        "            {icon: \"../../images/call/icon_call-ko.svg\", message: qsTr(\"Calls blocked to all the smartphones\") + trsl.empty}",
        "        ]",
        "    }",
        "",
        "    Repeater {",
        "        id: buttonsColumn",
        "        function blockCallFunction(action) {",
        "            switch (action) {",
        "            case AnsweringMachine.DisableAll:",
        "            case AnsweringMachine.InHouseOnly:",
        "            case AnsweringMachine.EnableAll:",
        "                answeringMachine.ipcCallMode = action",
        "                privateProps.selectedMode = action",
        "                pageContent.sourceComponent = message",
        "                break;",
        "            default:",
        "                dismissPopup()",
        "            }",
        "        }",
        "        model: [",
        "            {text: qsTr(\"Block calls to all the smartphones\") + trsl.empty, action: AnsweringMachine.DisableAll},",
        "            //{text: qsTr(\"Forward calls to the smartphones in the home\") + trsl.empty, action: AnsweringMachine.InHouseOnly},",
        "            {text: qsTr(\"Forward calls to all the smartphones\") + trsl.empty, action: AnsweringMachine.EnableAll},",
        "            {text: qsTr(\"Cancel\") + trsl.empty, action: -1},",
        "        ]",
        "    }",
        "}",
        "",
    ]
)
ORIGINAL_EVENT_MANAGER = "\n".join(
    [
        "import QtQuick 1.1",
        "",
        "Item {",
        "",
        "    Connections {",
        "        id: vctConnection",
        "        target: vctModel.binder.getObject(0)",
        "        onCallEnded: {",
        "            privateProps.switchingState = 0",
        "            global.audioState.disableState(AudioState.ScsVideoCall)",
        "            privateProps.callEnded()",
        "        }",
        "    }",
        "",
        "    Connections {",
        "        id: intercomConnection",
        "        target: intercomModel.binder.getObject(0)",
        "        onCallEnded: {",
        "            if (intercomModel.isIntercomCall) {",
        "                global.audioState.disableState(AudioState.ScsIntercomCall)",
        "            }",
        "            else if (intercomModel.isSipIntercomCall) {",
        "                global.audioState.disableState(AudioState.SipIntercomCall)",
        "            }",
        "",
        "            privateProps.callEnded()",
        "        }",
        "    }",
        "}",
        "",
    ]
)
SOURCE_INSTALLED_FILES = (
    "Alarm.qml",
    "HomeAssistant.qml",
    "C300XRingerControl.qml",
    "js/c300x_ha.js",
    "js/c300x_i18n.js",
    "js/c300x_memos.js",
)
PATCH_OUTPUT_SHA256 = {
    "MainApp.qml": "b755ebd730bd5b3f7a70dc301542b21119ef4f5b88463d3bc853314609fbcad2",
    "HomePage.qml": "21e67af70cdde0ed2809ba7ac7ffbd8d36c70979c12c1f231d6a05d1fa488032",
    "MemoPage.qml": "ec3b78970cd70a9ff1d48513b6658bc57323237258f4850b57bd42a5994a2e6a",
    "EventManager.qml": "0e0f7c38f08643c57b2d24d1c21f400a7104489c1f2c76ec406cda1a30e46d38",
    "Alarm.qml": "5052e346cbb8cb198ed3c8deb906b19437dfeddfeb33e877005b3d9f0241a573",
    "HomeAssistant.qml": "d7d056f33b0c396513f31a6c1c80ff3582dfafcf440ebfdc1e43d430325b93e5",
    "js/c300x_ha.js": "75bec040d64654f2898ff5dc64a93aa0bd120198b943d771f81bbd915d45d10b",
    "js/c300x_i18n.js": "2ea51304883ac9947206cdd2477a127f3740a0367d590a25db8bcb1e10bbc302",
    "js/c300x_memos.js": "13161e58509b6589bba6e689d7da08dff2c428722dcb51cbc25a785ffedbaba0",
}


def test_qml_patch_keeps_original_backup_across_reapply(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    first_status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "apply")
    assert first_status["state"] == "patched"
    assert first_status["changed_files"] > 0
    _assert_complete_gui_patch(gui_dir)

    second_status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "apply")
    assert second_status["state"] == "patched"
    assert second_status["changed_files"] == 0
    _assert_complete_gui_patch(gui_dir)

    assert (backup_dir / "MainApp.qml").read_text() == ORIGINAL_MAIN_APP
    assert (backup_dir / "HomePage.qml").read_text() == ORIGINAL_HOME_PAGE
    assert (backup_dir / "MemoPage.qml").read_text() == ORIGINAL_MEMO_PAGE
    assert not (backup_dir / "Components/Settings/CallBlockPopup.qml").exists()
    assert (backup_dir / "EventManager.qml").read_text() == ORIGINAL_EVENT_MANAGER
    assert not (backup_dir / "Alarm.qml").exists()
    assert not (backup_dir / "HomeAssistant.qml").exists()
    assert not (backup_dir / "js/c300x_ha.js").exists()
    assert not (backup_dir / "js/c300x_i18n.js").exists()
    assert not (backup_dir / "js/c300x_memos.js").exists()

    restored_status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "restore")
    assert restored_status["state"] == "original"
    assert restored_status["core_state"] == "patched"
    assert restored_status["changed_files"] > 0
    assert (gui_dir / "MainApp.qml").read_text() == ORIGINAL_MAIN_APP
    assert (gui_dir / "HomePage.qml").read_text() == ORIGINAL_HOME_PAGE
    assert (gui_dir / "MemoPage.qml").read_text() == ORIGINAL_MEMO_PAGE
    assert (gui_dir / "Components/Settings/CallBlockPopup.qml").read_text() == ORIGINAL_CALL_BLOCK_POPUP
    assert "c300xNotifyMediaClosed()" in (gui_dir / "EventManager.qml").read_text()
    assert not (gui_dir / "Alarm.qml").exists()
    assert not (gui_dir / "HomeAssistant.qml").exists()
    assert not (gui_dir / "js").exists()

    core_restored_status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-restore")
    assert core_restored_status["state"] == "original"
    assert core_restored_status["core_state"] == "original"
    assert core_restored_status["changed_files"] == 2
    assert not (gui_dir / "C300XRingerControl.qml").exists()
    assert (gui_dir / "EventManager.qml").read_text() == ORIGINAL_EVENT_MANAGER


def test_qml_patch_apply_installs_complete_function_patch(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "apply")

    assert status["state"] == "patched"
    assert status["patched"] is True
    assert status["core_state"] == "patched"
    assert status["core_patched"] is True
    assert status["media_user_label_state"] == "original"
    assert status["media_user_label_patched"] is False
    _assert_complete_gui_patch(gui_dir)


def test_qml_patch_apply_can_use_dynamic_home_page_buttons(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    status = _run_qml_patch(
        tmp_path,
        gui_dir,
        backup_dir,
        "apply",
        env_overrides={"C300X_QML_DYNAMIC_HOME_PAGE": "1"},
    )

    assert status["state"] == "patched"
    assert status["patched"] is True
    home_page = (gui_dir / "HomePage.qml").read_text()
    assert 'import "js/c300x_ha.js" as HAConfig' in home_page
    assert 'import "js/c300x_memos.js" as MemoSync' in home_page
    assert "function displayBridgeButtonCount()" in home_page
    assert "function refreshDisplayBridgeButtons()" in home_page
    assert "HAConfig.homeButtons" in home_page
    assert "+ 2 + page.displayBridgeButtonCount()" in home_page
    assert "id: homeAssistantButtonRow" not in home_page
    assert "visible: page.alarmButtonVisible" in home_page
    assert "visible: page.haButtonVisible" in home_page
    assert "function isVisible() { return visible }" in home_page
    assert home_page.index('objectName: "settingsButton"') < home_page.index(
        'objectName: "alarmButton"'
    )
    assert home_page.index('objectName: "alarmButton"') < home_page.index(
        'objectName: "haButton"'
    )


def test_qml_media_user_label_apply_installs_call_forwarding_label(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "media-user-label-apply")

    assert status["state"] == "original"
    assert status["patched"] is False
    assert status["core_state"] == "original"
    assert status["core_patched"] is False
    assert status["media_user_label_state"] == "patched"
    assert status["media_user_label_patched"] is True
    _assert_media_user_label_gui_patch(gui_dir)


def test_qml_core_apply_installs_media_and_ringer_hooks(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-apply")

    assert status["state"] == "original"
    assert status["patched"] is False
    assert status["core_state"] == "patched"
    assert status["core_patched"] is True
    assert status["changed_files"] == 2
    assert (gui_dir / "C300XRingerControl.qml").read_bytes() == (
        SOURCE_DIR / "C300XRingerControl.qml"
    ).read_bytes()
    assert (gui_dir / "MainApp.qml").read_text() == ORIGINAL_MAIN_APP
    assert (gui_dir / "HomePage.qml").read_text() == ORIGINAL_HOME_PAGE
    assert (gui_dir / "MemoPage.qml").read_text() == ORIGINAL_MEMO_PAGE
    assert "c300xNotifyMediaClosed()" in (gui_dir / "EventManager.qml").read_text()
    assert not (gui_dir / "Alarm.qml").exists()


def test_qml_core_status_detects_missing_call_end_hook(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)
    _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-apply")
    event_manager = (gui_dir / "EventManager.qml").read_text()
    (gui_dir / "EventManager.qml").write_text(
        event_manager.replace("            c300xNotifyMediaClosed()\n", "", 1)
    )

    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "status")

    assert status["core_state"] == "partial"
    assert status["core_patched"] is None


def test_qml_core_upgrade_corrects_legacy_media_port(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)
    _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-apply")
    event_manager = gui_dir / "EventManager.qml"
    event_manager.write_text(event_manager.read_text().replace(
        "http://127.0.0.1:8090/ui/media-closed",
        "http://127.0.0.1:8092/ui/media-closed",
    ))

    assert _run_qml_patch(tmp_path, gui_dir, backup_dir, "status")["core_state"] == "partial"
    upgraded = _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-apply")
    assert upgraded["core_patched"] is True
    assert upgraded["changed_files"] == 1
    _assert_media_hook_listener(event_manager.read_text())
    assert (backup_dir / "EventManager.qml").read_text() == ORIGINAL_EVENT_MANAGER
    assert _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-apply")["changed_files"] == 0
    _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-restore")
    assert event_manager.read_text() == ORIGINAL_EVENT_MANAGER


def test_qml_restore_all_removes_feature_core_and_media_user_label_patches(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    _run_qml_patch(tmp_path, gui_dir, backup_dir, "apply")
    _run_qml_patch(tmp_path, gui_dir, backup_dir, "media-user-label-apply")
    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "restore-all")

    assert status["state"] == "original"
    assert status["patched"] is False
    assert status["core_state"] == "original"
    assert status["core_patched"] is False
    assert status["media_user_label_state"] == "original"
    assert status["media_user_label_patched"] is False
    assert (gui_dir / "MainApp.qml").read_text() == ORIGINAL_MAIN_APP
    assert (gui_dir / "HomePage.qml").read_text() == ORIGINAL_HOME_PAGE
    assert (gui_dir / "MemoPage.qml").read_text() == ORIGINAL_MEMO_PAGE
    assert (gui_dir / "Components/Settings/CallBlockPopup.qml").read_text() == ORIGINAL_CALL_BLOCK_POPUP
    assert (gui_dir / "EventManager.qml").read_text() == ORIGINAL_EVENT_MANAGER


def test_qml_core_upgrade_adds_ringer_hook_without_replacing_original_backup(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)
    _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-apply")
    event_manager = gui_dir / "EventManager.qml"
    event_manager.write_text(event_manager.read_text().replace(
        "    C300XRingerControl {}\n", "",
    ).replace("http://127.0.0.1:8090/ui/media-closed", "http://127.0.0.1:8092/ui/media-closed"))
    (gui_dir / "C300XRingerControl.qml").unlink()
    assert _run_qml_patch(tmp_path, gui_dir, backup_dir, "status")["core_state"] == "partial"
    upgraded = _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-apply")
    assert upgraded["core_patched"] is True
    assert upgraded["changed_files"] == 2
    assert event_manager.read_text().count("C300XRingerControl {}") == 1
    _assert_media_hook_listener(event_manager.read_text())
    assert (backup_dir / "EventManager.qml").read_text() == ORIGINAL_EVENT_MANAGER
    assert _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-apply")["changed_files"] == 0


def test_qml_restore_all_handles_core_only_patch(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-apply")
    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "restore-all")

    assert status["state"] == "original"
    assert status["core_state"] == "original"
    assert status["changed_files"] == 2
    assert not (gui_dir / "C300XRingerControl.qml").exists()
    assert not (backup_dir / "MainApp.qml").exists()
    assert (gui_dir / "EventManager.qml").read_text() == ORIGINAL_EVENT_MANAGER


def test_qml_patch_generated_output_hashes_are_stable(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "apply")

    assert status["state"] == "patched"
    assert {
        relative_path: _sha256(gui_dir / relative_path)
        for relative_path in PATCH_OUTPUT_SHA256
    } == PATCH_OUTPUT_SHA256


def test_home_assistant_qml_keeps_empty_state_label_blank() -> None:
    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )
    dashboard_js = (ROOT / "device_qml" / "js/c300x_ha.js").read_text(
        encoding="utf-8"
    )
    item_detail_body = home_assistant_qml[
        home_assistant_qml.index("function itemDetail") :
        home_assistant_qml.index("function itemColor")
    ]
    dashboard_items_body = dashboard_js[
        dashboard_js.index("function dashboardItems") :
        dashboard_js.index("function dashboardSliders")
    ]
    dashboard_choices_body = dashboard_js[
        dashboard_js.index("function dashboardChoices") :
        dashboard_js.index("function dashboardImages")
    ]

    assert 'item.hasOwnProperty("state_label")' in item_detail_body
    assert item_detail_body.index('item.hasOwnProperty("state_label")') < (
        item_detail_body.index('uiText("execute")')
    )
    assert 'source[i].hasOwnProperty("state_label")' in dashboard_items_body
    assert 'source[i].state_label || source[i].label || ""' not in dashboard_items_body
    assert '"options": dashboardChoiceOptions(source[i].options)' in dashboard_choices_body


def test_home_assistant_buttons_keep_static_press_feedback() -> None:
    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )
    button_component_body = home_assistant_qml[
        home_assistant_qml.index("id: mixedButtonTileComponent") :
        home_assistant_qml.index("id: mixedSliderTileComponent")
    ]

    assert "source: tileMouse.pressed" in button_component_body
    assert "Behavior on" not in button_component_body
    assert "NumberAnimation" not in button_component_body


def test_home_assistant_qml_renders_select_entities_as_choices() -> None:
    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )
    dashboard_js = (ROOT / "device_qml" / "js/c300x_ha.js").read_text(
        encoding="utf-8"
    )

    assert "id: mixedChoiceTileComponent" in home_assistant_qml
    assert "id: choiceGrid" not in home_assistant_qml
    assert "Api.dashboardChoiceAction" in home_assistant_qml
    assert "Api.dashboardChoiceOptionLabel(modelData)" in home_assistant_qml
    assert "Api.dashboardChoiceOptionValue(modelData)" in home_assistant_qml
    assert 'assignDashboardValue(pageItem, "items", dashboardWeatherPlaced(dashboardMixedItems(pageData.items), pageData.weather))' in dashboard_js
    assert "function dashboardChoiceOptions" in dashboard_js
    assert "+ encodeURIComponent(item.entity_id)" in dashboard_js
    assert 'dashboardControl(item, {command: ""}, option, statusItem, pageItem)' in dashboard_js
    assert '"&option=" + encodeURIComponent(value)' in dashboard_js
    assert 'item.entity_id + ":select:" + option' not in dashboard_js


def test_home_assistant_mixed_dashboard_preserves_image_kind() -> None:
    dashboard_js = (ROOT / "device_qml" / "js/c300x_ha.js").read_text(
        encoding="utf-8"
    )
    dashboard_mixed_body = dashboard_js[
        dashboard_js.index("function dashboardMixedItems") :
        dashboard_js.index("function dashboardSliders")
    ]
    dashboard_images_body = dashboard_js[
        dashboard_js.index("function dashboardImages") :
        dashboard_js.index("function imageSource")
    ]

    assert 'kind === "image"' in dashboard_mixed_body
    assert '"kind": "image"' in dashboard_images_body


def test_home_assistant_mixed_dashboard_uses_two_columns_for_standard_tiles() -> None:
    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )
    mixed_items_body = home_assistant_qml[
        home_assistant_qml.rindex("Flow {", 0, home_assistant_qml.index("id: itemColumn")) :
        home_assistant_qml.index('text: items.length === 0')
    ]

    assert "Flow {" in mixed_items_body
    assert "property int tileWidth: (width - spacing) / 2" in mixed_items_body
    # An entity can match several keys at once: dashboard.py gives number and
    # select entities controls as well as a slider/choice kind. Width, height and
    # the Loader must therefore agree on which key wins, or a tile gets the size
    # of one component and the content of another.
    delegate = mixed_items_body[mixed_items_body.index("id: mixedTile") :]

    def _expression(prefix: str) -> str:
        return delegate.split(prefix)[1].split("\n")[0]

    def _order(expression: str) -> list[str]:
        keys = ("isSensor", "hasControls", "isImage", "isChoice", "isSlider")
        return sorted((key for key in keys if key in expression), key=expression.index)

    width_expression = _expression("width: ")
    assert "itemColumn.tileWidth" in width_expression
    for expression in (width_expression, _expression("height: "), _expression("sourceComponent: ")):
        assert _order(expression)[:2] == ["isSensor", "hasControls"], expression
    assert "Loader {" in mixed_items_body
    assert "sourceComponent:" in mixed_items_body
    assert "visible: mixedTile.is" not in mixed_items_body
    assert "visible: !mixedTile.is" not in mixed_items_body


def test_home_assistant_control_tiles_open_from_the_tile_with_a_single_switch() -> None:
    """Control tiles must not need a separate arrow button to open their detail.

    The tile background carries the open gesture, exactly like a sensor tile, and
    the only control on the half-height tile is the on/off switch. Tiles that
    carry their own buttons are the separate full-height component, so this
    one stays as small as it is.
    """

    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )
    overview = home_assistant_qml[
        home_assistant_qml.index("id: controlOverview") :
        home_assistant_qml.index("id: sensorOverview")
    ]

    assert "BeepingMouseArea {" in overview
    assert "onClicked: openDetails(tileItem)" in overview
    assert "anchors.fill: parent" in overview
    # The chevron stays as the "has a submenu" marker, like the sensor tile, but
    # it is a plain label now: the tile itself carries the open gesture and there
    # is no separate arrow button and no quick-control repeater.
    assert overview.count("\\u203a") == 1
    assert "BasicButton {" in overview
    assert "Repeater {" not in overview
    assert overview.count("BeepingMouseArea {") == 1
    # Exactly one toggle, drawn as the shared firmware switch widget.
    assert overview.count("onTouched:") == 1
    assert "style: CheckableButtonStyle {" in overview
    assert 'dashboardControlByCommand(tileItem, "toggle")' in overview
    assert "images/onoff_button.svg" not in overview


def test_home_assistant_tile_size_is_configurable_per_entity() -> None:
    """Width and height come from the entity's settings, defaulting to its type.

    Nothing here can execute QtQuick, so the contract is checked on the source:
    an unconfigured tile must keep the exact size it had before the setting
    existed, and each size must load the component that was laid out for it.
    """

    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )
    delegate = home_assistant_qml[home_assistant_qml.index("id: mixedTile") :]

    assert 'property string sizeW: tileItem.tile_width || ""' in delegate
    assert 'property string sizeH: tileItem.tile_height || ""' in delegate
    # Automatic height: sensors stay tall, everything else stays short.
    assert 'property bool tall: sizeH === "full" || (sizeH === "" && isSensor)' in delegate
    width = delegate.split("width: ")[1].split("\n")[0]
    height = delegate.split("height: ")[1].split("\n")[0]
    source = delegate.split("sourceComponent: ")[1].split("\n")[0]
    assert width.startswith(
        'isSensor || hasControls ? (sizeW === "full" ? itemColumn.width : itemColumn.tileWidth)'
    )
    assert height.startswith("isSensor || hasControls ? (tall ? 94 : 64)")
    # Plain switch, button and entity tiles keep 58/64 px unless configured.
    assert height.endswith('(tall ? 94 : (sizeH === "half" || isSlider || isButton ? 64 : 58)))))')
    assert "mixedTile.isSensor ? (mixedTile.tall ? sensorOverview : compactSensorOverview)" in source
    assert "mixedTile.hasControls ? (mixedTile.tall ? tallControlOverview : controlOverview)" in source


def test_home_assistant_full_height_control_tile_carries_its_buttons() -> None:
    """The full-height tile adds the entity's buttons without losing the submenu."""

    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )
    tall = home_assistant_qml[
        home_assistant_qml.index("id: tallControlOverview") :
        home_assistant_qml.index("id: notificationDetails")
    ]
    compact = home_assistant_qml[
        home_assistant_qml.index("id: compactSensorOverview") :
        home_assistant_qml.index("id: tallControlOverview")
    ]

    # The background still opens the submenu and is declared before the
    # buttons, so they sit above it and take their own touches.
    assert tall.index("onClicked: openDetails(tallTile.tileItem)") < tall.index("Repeater {")
    assert "property variant quickButtons: Api.dashboardQuickControls(tileItem)" in tall
    assert "model: tallTile.quickButtons.length" in tall
    assert "property variant quick: tallTile.quickButtons[index] || ({})" in tall
    assert "onClicked: if (usable) quickAction(tallTile.tileItem, quick)" in tall
    # Buttons obey the same gate as the switch and are dimmed while it is
    # closed or their step has nothing to start from. Only the latter lets the
    # touch through to the background and its submenu: a quick second press
    # while a command is in flight is taken and ignored, not turned into a
    # submenu. They show a registered touch.
    assert tall.count("enabled: tallTile.controlsEnabled") == 1
    assert "property bool usable: tallTile.controlsEnabled && quickUsable(quick, control)" in tall
    assert "opacity: usable ? 1 : 0.45" in tall
    assert "enabled: quickUsable(quick, control)" in tall
    assert "enabled: usable" not in tall
    assert "quickMouse.pressed ?" in tall
    # The reading stays a reading: feedback reaches it as colour only.
    assert "text: itemDetail(tallTile.tileItem) + trsl.empty" in tall
    assert "color: readingColor(tallTile.tileItem)" in tall
    assert "feedbackText(" not in tall
    assert tall.count("onTouched:") == 1
    assert tall.count("\\u203a") == 1

    assert "onClicked: openDetails(tileItem)" in compact
    assert "text: itemDetail(tileItem)" in compact
    assert "color: detailColor(tileItem)" in compact


def test_home_assistant_weather_card_is_an_ordered_tile() -> None:
    """The weather card sorts with the tiles instead of sitting above them."""

    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )
    flow = home_assistant_qml[home_assistant_qml.index("id: itemColumn") :]
    column_head = home_assistant_qml[
        home_assistant_qml.index("id: contentColumn") : home_assistant_qml.index("id: itemColumn")
    ]
    delegate = flow[flow.index("id: mixedTile") :]

    # Exactly one card, and it lives in the flow as a component.
    assert home_assistant_qml.count("id: weatherCard") == 1
    assert "id: weatherCard" not in column_head
    assert flow.index("id: weatherTileComponent") < flow.index("id: weatherCard")
    assert flow.index("id: weatherCard") < flow.index("id: mixedImageTileComponent")
    assert 'property bool isWeather: tileItem.kind === "weather"' in delegate
    assert "isWeather ? 166" in delegate.split("height: ")[1].split("\n")[0]
    assert "mixedTile.isWeather ? weatherTileComponent" in delegate
    # A read-only card must not dim while a command is pending.
    assert "mixedTile.isSensor || mixedTile.isWeather || (dashboardOnline" in delegate


def test_home_assistant_toggles_use_the_firmware_switch_widget() -> None:
    """Every on/off toggle must look like the firmware switch.

    The tile overview and the detail summary show the same entity, so they must
    not disagree on what a toggle looks like. The old icon-on-a-list-button
    artwork is retired everywhere.
    """

    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )
    summary_toggle = home_assistant_qml[
        home_assistant_qml.index("id: summaryToggle") :
        home_assistant_qml.index("id: summaryToggle") + 1600
    ]

    assert "images/onoff_button.svg" not in home_assistant_qml
    assert "style: CheckableButtonStyle {" in summary_toggle
    assert 'dashboardControlByCommand(selectedItem, "toggle")' in summary_toggle
    # The switch renders its own state, so the green state bar is redundant.
    assert 'color: "#58d68d"' not in summary_toggle

    # Every switch declares the style inline, because the firmware never assigns
    # a named Component to a style property and CheckableButtonStyle resolves
    # `control` through the Loader inside BasicButton - untestable off-device.
    # The four blocks (switch tile, half- and full-height control tile, detail
    # summary) must stay byte-identical so they cannot drift apart.
    blocks = []
    for match in re.finditer(
        r"( *)style: CheckableButtonStyle \{\n(.*?)\n\1\}", home_assistant_qml, re.DOTALL
    ):
        blocks.append(dedent(match.group(2)))
    assert len(blocks) == 4, len(blocks)
    assert len(set(blocks)) == 1, blocks
    assert "images/ringtones/switch-bg_btn.svg" in blocks[0]


def test_home_assistant_buttons_show_that_a_touch_registered() -> None:
    """Every real button must swap artwork while pressed.

    The device has no haptic feedback, so a button whose image stays put during
    a touch reads as "not registered" and invites double taps. Sites where the
    same artwork means "selected" keep their selected/unselected pair instead.
    """

    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )

    assert home_assistant_qml.count('source: "images/settings/list_btn.svg"') == 0
    assert home_assistant_qml.count("images/settings/list_btn_p.svg") == 5
    assert (
        home_assistant_qml.count(
            '? "images/settings/list_btn.svg" : "images/settings/act_btn.svg"'
        )
        == 3
    )
    for mouse_id in (
        "notificationActionMouse",
        "coverControlMouse",
        "controlButtonMouse",
        "adjustMouse",
        "notificationBannerMouse",
    ):
        assert f"id: {mouse_id}" in home_assistant_qml
        assert f"{mouse_id}.pressed ?" in home_assistant_qml


def test_home_assistant_reads_each_piece_of_state_once() -> None:
    """Hot paths must not re-read variant properties or recompute feedback.

    Reading a QML variant property converts the stored value back into
    JavaScript, so indexing one inside a loop converts it once per iteration.
    feedbackText() walks the feedback list, so a tile that asks for it twice -
    once for its text, once for its colour - walks it twice per refresh.
    """

    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )
    feedback_key = home_assistant_qml[
        home_assistant_qml.index("function feedbackKey") :
        home_assistant_qml.index("function feedbackText")
    ]
    refresh_selected = home_assistant_qml[
        home_assistant_qml.index("function refreshSelectedItem") :
        home_assistant_qml.index("function startWatch")
    ]

    assert "controlFeedback[i]" not in feedback_key
    assert "controlFeedback.length" not in feedback_key
    assert "items[i]" not in refresh_selected
    assert "items.length" not in refresh_selected

    button_tile = home_assistant_qml[
        home_assistant_qml.index("id: mixedButtonTileComponent") :
        home_assistant_qml.index("id: mixedSliderTileComponent")
    ]
    assert button_tile.count("feedbackText(tileItem)") == 1
    assert "property string feedback: feedbackText(tileItem)" in button_tile
    assert "text: (feedback || itemDetail(tileItem))" in button_tile
    assert "color: feedback ?" in button_tile

    # A control tile shows the entity reading, which command feedback must never
    # replace: controlFeedback entries are never cleared, so a single toggle
    # would pin the tile to "state confirmed", and going offline would hide the
    # retained last-known value. Transient feedback reaches it as colour only.
    control_tile = home_assistant_qml[
        home_assistant_qml.index("id: controlOverview") :
        home_assistant_qml.index("id: sensorOverview")
    ]
    assert "text: itemDetail(tileItem) + trsl.empty" in control_tile
    assert "color: readingColor(tileItem)" in control_tile
    assert "feedbackText(" not in control_tile
    reading_color = home_assistant_qml[
        home_assistant_qml.index("function readingColor") :
        home_assistant_qml.index("function feedbackColor")
    ]
    assert '=== "state_confirmed"' not in reading_color
    assert '=== "sending"' in reading_color
    assert '=== "action_error"' in reading_color


def test_display_bridge_js_connection_cleanup_does_not_keep_stale_longpolls() -> None:
    for relative_path in ("js/c300x_ha.js", "js/c300x_memos.js"):
        script = (ROOT / "device_qml" / relative_path).read_text(encoding="utf-8")
        cleanup_body = script[
            script.index("function cleanupConnections") :
        ]

        assert (
            "longPoll === true && "
            in cleanup_body
        )
        assert "connections" in cleanup_body
        assert "eventRequest" in cleanup_body
        assert "eventWatching === true" in cleanup_body
        assert "removeConnection(xhr)" in script[script.index("function getJson") :]


def test_home_page_message_watch_stops_on_hide(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "apply")
    assert status["state"] == "patched"

    home_page = (gui_dir / "HomePage.qml").read_text(encoding="utf-8")
    start_body = home_page[
        home_page.index("function startMessageNotificationWatch") :
        home_page.index("function stopMessageNotificationWatch")
    ]

    assert "onVisibleChanged: {" in home_page
    assert "if (!visible) {" in home_page
    assert "stopMessageNotificationWatch()" in home_page
    assert start_body.index("stopMessageNotificationWatch()") < start_body.index(
        "MemoSync.startEventWatch(handleMessageNotificationEvent)"
    )


def test_alarm_quick_action_keeps_label_and_confirmed_state_separate() -> None:
    alarm_qml = (ROOT / "device_qml" / "Alarm.qml").read_text(encoding="utf-8")
    detail_body = alarm_qml[
        alarm_qml.index("function alarmPageItemDetail") :
        alarm_qml.index("function alarmPageItemColor")
    ]
    quick_tile_body = alarm_qml[
        alarm_qml.index("id: stairMouse") - 1400 :
        alarm_qml.index("id: stairMouse")
    ]

    assert 'alarmPageItem.state_label || ""' in detail_body
    assert "font.pixelSize: alarmPageItemName().length > 18 ? 17 : 20" in quick_tile_body
    assert "anchors.topMargin: alarmPageItemDetail().length > 0 ? 5 : 13" in quick_tile_body
    assert "textFormat: Text.PlainText" in quick_tile_body
    # QtQuick 1.1 cannot store JS null in a variant property, so this gate
    # must stay on truthiness. See tests/test_qml_variant_null_contract.py.
    assert "visible: alarmPageItem ? true : false" in alarm_qml


def test_alarm_quick_action_does_not_refresh_home_assistant_dashboard() -> None:
    alarm_qml = (ROOT / "device_qml" / "Alarm.qml").read_text(encoding="utf-8")
    dashboard_js = (ROOT / "device_qml" / "js/c300x_ha.js").read_text(
        encoding="utf-8"
    )

    assert "Api.dashboardAction(alarmPageItem, status, page, false)" in alarm_qml
    assert "function dashboardAction(item, statusItem, pageItem, refreshDashboard)" in dashboard_js
    assert "if (refreshDashboard !== false)" in dashboard_js


def test_qml_i18n_catalogs_have_identical_key_sets() -> None:
    i18n_source = (SOURCE_DIR / "js/c300x_i18n.js").read_text(encoding="utf-8")

    text_keys = _js_object_keys(i18n_source, "EN")
    assert _js_object_keys(i18n_source, "DE") == text_keys
    assert _js_object_keys(i18n_source, "IT") == text_keys
    assert _js_object_keys(i18n_source, "FR") == text_keys

    weather_keys = _js_object_keys(i18n_source, "WEATHER_EN")
    assert _js_object_keys(i18n_source, "WEATHER_DE") == weather_keys
    assert _js_object_keys(i18n_source, "WEATHER_IT") == weather_keys
    assert _js_object_keys(i18n_source, "WEATHER_FR") == weather_keys


def test_qml_patch_apply_reports_reload_failure_without_patched_state(
    tmp_path: Path,
) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    result = _run_qml_patch_raw(
        tmp_path,
        gui_dir,
        backup_dir,
        "apply",
        env_overrides={
            "C300X_QML_RELOAD_GUI": "1",
            "C300X_QML_GUI_RELOAD_DELAY_SECONDS": "0",
            "C300X_QML_GUI_WRAPPER": str(tmp_path / "missing-gui-wrapper"),
        },
    )

    result.check_returncode()
    status = json.loads(result.stdout)
    assert status["state"] == "reload_failed"
    assert status["patched"] is None
    _assert_complete_gui_patch(gui_dir)


def test_qml_patch_remounts_ro_after_write_action(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    mount_log = tmp_path / "mount.log"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)
    env = _fake_mount_env(tmp_path, mount_log)

    result = _run_qml_patch_raw(
        tmp_path,
        gui_dir,
        backup_dir,
        "apply",
        no_remount=False,
        env_overrides=env,
    )

    assert result.returncode == 0
    assert mount_log.read_text().splitlines() == [
        "-o remount,rw /",
        "-o remount,ro /",
    ]


def test_qml_patch_does_not_remount_when_reapply_is_identical(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    mount_log = tmp_path / "mount.log"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)
    env = _fake_mount_env(tmp_path, mount_log)

    first_result = _run_qml_patch_raw(
        tmp_path,
        gui_dir,
        backup_dir,
        "apply",
        no_remount=False,
        env_overrides=env,
    )
    first_result.check_returncode()
    mount_log.write_text("")

    second_status = _run_qml_patch(
        tmp_path,
        gui_dir,
        backup_dir,
        "apply",
        no_remount=False,
        env_overrides=env,
    )

    assert second_status["changed_files"] == 0
    assert mount_log.read_text() == ""


def test_qml_patch_remounts_ro_after_failed_write_action(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    mount_log = tmp_path / "mount.log"
    source_dir = tmp_path / "missing-source"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)
    env = _fake_mount_env(tmp_path, mount_log)

    result = _run_qml_patch_raw(
        tmp_path,
        gui_dir,
        backup_dir,
        "apply",
        no_remount=False,
        source_dir=source_dir,
        env_overrides=env,
    )

    assert result.returncode != 0
    assert not mount_log.exists()


def test_qml_patch_status_detects_partial_function_patch(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)
    (gui_dir / "Alarm.qml").write_text("headerLabel: \"Alarmanlage\"\n")

    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "status")

    assert status["state"] == "partial"
    assert status["patched"] is None


def test_qml_patch_refuses_patched_home_page_without_original_backup(
    tmp_path: Path,
) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)
    (gui_dir / "HomePage.qml").write_text(
        ORIGINAL_HOME_PAGE + "\n            Row { id: homeAssistantButtonRow }\n"
    )

    result = _run_qml_patch_raw(tmp_path, gui_dir, backup_dir, "apply")

    assert result.returncode != 0
    assert "already patched" in result.stderr
    assert not (backup_dir / "HomePage.qml").exists()


def test_qml_patch_preserves_source_files_at_runtime(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    source_dir = tmp_path / "source"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)
    _copy_source_tree(source_dir)
    (source_dir / "HomePage.qml").write_text("old generated stock copy\n")
    (source_dir / "MemoPage.qml").write_text("old generated stock copy\n")

    status = _run_qml_patch(
        tmp_path,
        gui_dir,
        backup_dir,
        "apply",
        source_dir=source_dir,
    )

    assert status["state"] == "patched"
    assert (source_dir / "HomePage.qml").exists()
    assert (source_dir / "MemoPage.qml").exists()
    _assert_complete_gui_patch(gui_dir, source_dir=source_dir)


def test_qml_patch_restore_refuses_to_delete_stock_files_without_backups(
    tmp_path: Path,
) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)
    (gui_dir / "Alarm.qml").write_text("generated page\n")

    result = _run_qml_patch_raw(tmp_path, gui_dir, backup_dir, "restore")

    assert result.returncode != 0
    assert "No original backup available for MainApp.qml" in result.stderr
    assert (gui_dir / "MainApp.qml").read_text() == ORIGINAL_MAIN_APP
    assert (gui_dir / "HomePage.qml").read_text() == ORIGINAL_HOME_PAGE
    assert (gui_dir / "MemoPage.qml").read_text() == ORIGINAL_MEMO_PAGE


def _run_qml_patch(
    tmp_path: Path,
    gui_dir: Path,
    backup_dir: Path,
    action: str,
    *,
    no_remount: bool = True,
    source_dir: Path = SOURCE_DIR,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, object]:
    result = _run_qml_patch_raw(
        tmp_path,
        gui_dir,
        backup_dir,
        action,
        no_remount=no_remount,
        source_dir=source_dir,
        env_overrides=env_overrides,
    )
    result.check_returncode()
    return json.loads(result.stdout)


def _run_qml_patch_raw(
    tmp_path: Path,
    gui_dir: Path,
    backup_dir: Path,
    action: str,
    *,
    no_remount: bool = True,
    source_dir: Path = SOURCE_DIR,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "C300X_QML_GUI_DIR": str(gui_dir),
        "C300X_QML_SOURCE_DIR": str(source_dir),
        "C300X_QML_BACKUP_DIR": str(backup_dir),
        "C300X_QML_NO_REMOUNT": "1" if no_remount else "0",
        "C300X_QML_RELOAD_GUI": "0",
        "C300X_QML_GUI_ROOT": str(tmp_path),
    }
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(SCRIPT), action],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def _write_original_gui(gui_dir: Path) -> None:
    (gui_dir / "MainApp.qml").write_text(ORIGINAL_MAIN_APP)
    (gui_dir / "HomePage.qml").write_text(ORIGINAL_HOME_PAGE)
    (gui_dir / "MemoPage.qml").write_text(ORIGINAL_MEMO_PAGE)
    (gui_dir / "Components/Settings").mkdir(parents=True, exist_ok=True)
    (gui_dir / "Components/Settings/CallBlockPopup.qml").write_text(ORIGINAL_CALL_BLOCK_POPUP)
    (gui_dir / "EventManager.qml").write_text(ORIGINAL_EVENT_MANAGER)


def _copy_source_tree(source_dir: Path) -> None:
    for relative_path in SOURCE_INSTALLED_FILES:
        source_file = SOURCE_DIR / relative_path
        target_file = source_dir / relative_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)


def _assert_complete_gui_patch(
    gui_dir: Path,
    *,
    source_dir: Path = SOURCE_DIR,
) -> None:
    for relative_path in SOURCE_INSTALLED_FILES:
        assert (gui_dir / relative_path).read_bytes() == (
            source_dir / relative_path
        ).read_bytes()

    home_page = (gui_dir / "HomePage.qml").read_text()
    assert "originalHomeSetup()" in home_page
    assert 'import "js/c300x_ha.js" as HAConfig' not in home_page
    assert 'import "js/c300x_memos.js" as MemoSync' in home_page
    assert "function refreshDisplayBridgeButtons()" not in home_page
    assert "function startMessageNotificationWatch()" in home_page
    assert "function stopMessageNotificationWatch()" in home_page
    assert "MemoSync.syncHomeNotifications(page)" in home_page
    assert "MemoSync.startEventWatch(handleMessageNotificationEvent)" in home_page
    assert 'event.topic === "memos"' in home_page
    assert 'event.topic === "answering_machine.messages"' in home_page
    assert "id: homeAssistantButtonRow" in home_page
    assert "width: buttonPrototype.width * 2 + foobar.spacing" in home_page
    assert "spacing: foobar.spacing" in home_page
    assert "anchors.left: foobar.right" not in home_page
    assert "notificationsCount: page.unreadMessagesCount()" in home_page
    assert "notificationsCount: page.unreadMemosCount()" in home_page
    assert "visible: page.alarmButtonVisible" not in home_page
    assert "visible: page.haButtonVisible" not in home_page
    assert home_page.index('objectName: "settingsButton"') < home_page.index(
        'objectName: "alarmButton"'
    )
    assert home_page.index('objectName: "alarmButton"') < home_page.index(
        'objectName: "haButton"'
    )
    assert 'pressedIcon: "images/keylock_icon-small_p.svg"' in home_page
    assert 'defaultIcon: "images/keylock_icon-small.svg"' in home_page
    assert 'pressedIcon: "images/call/icon_call-home_p.svg"' in home_page
    assert 'defaultIcon: "images/call/icon_call-home.svg"' in home_page
    assert 'trsl.language === "de" ? "Alarmanlage"' in home_page
    assert 'trsl.language === "it" ? "Allarme"' in home_page
    assert 'trsl.language === "fr" ? "Alarme"' in home_page
    assert "buttonHolder.buttonCount() === 5" in home_page
    assert "console.log(" not in home_page

    memo_page = (gui_dir / "MemoPage.qml").read_text()
    assert "originalMemoOpen()" in memo_page
    assert 'import "js/c300x_memos.js" as MemoSync' in memo_page
    assert "function aboutToShow()" in memo_page
    assert "MemoSync.syncMemoModel(page, AnsweringMessage.TextMemo)" in memo_page

    event_manager = (gui_dir / "EventManager.qml").read_text()
    assert "function c300xNotifyMediaClosed()" in event_manager
    assert event_manager.count("C300XRingerControl {}") == 1
    _assert_media_hook_listener(event_manager)
    assert event_manager.count("c300xNotifyMediaClosed()") == 3
    assert event_manager.index("c300xNotifyMediaClosed()") < event_manager.index(
        "privateProps.switchingState = 0"
    )
    assert event_manager.rindex("c300xNotifyMediaClosed()") < event_manager.index(
        "global.audioState.disableState(AudioState.ScsIntercomCall)"
    )

    main_app = (gui_dir / "MainApp.qml").read_text()
    assert (
        "            memoPage,\n"
        "            alarmPage,\n"
        "            haPage,\n"
        "            settingsPage,"
    ) in main_app
    assert (
        '    PageLoader {\n'
        '        id: alarmPage\n'
        '        sourceUrl: "Alarm.qml"\n'
        '    }\n\n'
        '    PageLoader {\n'
        '        id: haPage\n'
        '        sourceUrl: "HomeAssistant.qml"\n'
        '    }\n\n'
        '    PageLoader {\n'
        '        id: settingsPage'
    ) in main_app
    assert main_app.count("            alarmPage,") == 1
    assert main_app.count("            haPage,") == 1
    assert main_app.count('id: alarmPage') == 1
    assert main_app.count('id: haPage') == 1
    assert main_app.count('sourceUrl: "Alarm.qml"') == 1
    assert main_app.count('sourceUrl: "HomeAssistant.qml"') == 1


def _assert_media_user_label_gui_patch(gui_dir: Path) -> None:
    call_block_popup = (gui_dir / "Components/Settings/CallBlockPopup.qml").read_text()
    assert "original" not in call_block_popup
    assert "Anrufe an Home Assistant weitergeleitet" in call_block_popup
    assert "Chiamate inoltrate a Home Assistant" in call_block_popup
    assert "Appels renvoyes vers Home Assistant" in call_block_popup
    assert "Calls forwarded to Home Assistant" in call_block_popup
    assert "Anrufe an Home Assistant" in call_block_popup
    assert "Inoltra chiamate a Home Assistant" in call_block_popup
    assert "Renvoyer les appels vers Home Assistant" in call_block_popup
    assert "Forward calls to Home Assistant" in call_block_popup
    assert "action: AnsweringMachine.InHouseOnly" in call_block_popup
    assert 'qsTr("Forward calls to the smartphones in the home")' not in call_block_popup
    assert "answeringMachine.ipcCallMode = action" in call_block_popup


def _fake_mount_env(tmp_path: Path, mount_log: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_mount = bin_dir / "mount"
    fake_mount.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {mount_log}\n"
        "exit 0\n"
    )
    fake_mount.chmod(0o700)
    return {"PATH": f"{bin_dir}:{os.environ['PATH']}"}


def _assert_media_hook_listener(event_manager: str) -> None:
    config = json.loads((ROOT / "native_agent/config.example.json").read_text())
    ui_port = config["listen"]["uiPort"]
    assert f'request.open("GET", "http://127.0.0.1:{ui_port}/ui/media-closed", true)' in event_manager


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _js_object_keys(source: str, object_name: str) -> set[str]:
    match = re.search(
        rf"^var {re.escape(object_name)} = \{{\n(?P<body>.*?)^\}}$",
        source,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, object_name
    return set(re.findall(r'^\s+"([^"]+)":', match.group("body"), re.MULTILINE))


def test_home_assistant_ages_command_feedback_out() -> None:
    """Command feedback must not outlive what it says.

    Nothing removes a controlFeedback entry: setDashboardFeedback replaces only
    the entry for the same entity, and aboutToHide keeps the list so an
    unconfirmed command is still reported when the page is reopened. A command
    that Home Assistant accepts but never reflects would therefore keep its
    tile on "action sent" for the rest of the session. The shipped page has to
    age the entries where it reads them, because the dashboard deliberately
    runs no periodic timer.
    """

    dashboard_js = (ROOT / "device_qml" / "js" / "c300x_ha.js").read_text(
        encoding="utf-8"
    )
    home_assistant_qml = (ROOT / "device_qml" / "HomeAssistant.qml").read_text(
        encoding="utf-8"
    )

    assert '"expected": expected' not in dashboard_js
    assert "expected: expected || null, at: Date.now()" in dashboard_js
    assert "function feedbackState(entry)" in dashboard_js
    assert "Api.feedbackState(feedback[i])" in home_assistant_qml

    feedback_state = dashboard_js[
        dashboard_js.index("function feedbackState") :
        dashboard_js.index("function dashboardExpectation")
    ]
    assert "FEEDBACK_DISCARD_MS) return \"\"" in feedback_state
    assert 'FEEDBACK_UNCONFIRMED_MS) return "state_unconfirmed"' in feedback_state

    # A confirmation has to be stamped afresh, or it would be discarded on the
    # command's stamp instead of its own.
    confirm = dashboard_js[
        dashboard_js.index("function confirmDashboardFeedback") :
        dashboard_js.index("function dashboardControl")
    ]
    assert 'state: "state_confirmed", expected: null, at: Date.now()' in confirm
    # An entry that has already aged out must not come back as a confirmation.
    assert 'feedbackState(feedback[i]) === ""' in confirm


def test_display_requests_cannot_collide_in_the_agent() -> None:
    """Only one display request may be in flight towards Home Assistant.

    The agent forwards /ui/state, /homeassistant, /ui/action and
    /ui/alarm/command to Home Assistant and keeps exactly one of them in
    flight: forward_to_homeassistant stores the client socket in
    display_client_fd and answers a second request with 503
    display_command_pending. All four routes are loopback only and every one of
    them is reached from this library, which QML shares as a single .pragma
    library instance across the home, alarm and dashboard pages, so the
    collision is removed by serialising there. The event long poll must stay
    outside that queue: it blocks for seconds by design and has its own waiter
    slots in the agent.
    """

    dashboard_js = (ROOT / "device_qml" / "js" / "c300x_ha.js").read_text(
        encoding="utf-8"
    )

    assert "var forwardActive = null" in dashboard_js
    assert "function finishForward(xhr)" in dashboard_js

    get_json = dashboard_js[
        dashboard_js.index("function getJson(") :
        dashboard_js.index("function sendForward(")
    ]
    assert "forwardQueue.push(" in get_json
    assert "new XMLHttpRequest()" not in get_json, "a busy slot must not be bypassed"

    send_forward = dashboard_js[
        dashboard_js.index("function sendForward(") :
        dashboard_js.index("function finishForward(")
    ]
    # Without the finally, a page callback that throws would keep the slot and
    # the display would stop talking to the agent for good.
    assert "} finally {" in send_forward
    assert "finishForward(xhr)" in send_forward

    # The long poll builds its own request and is never queued behind the rest.
    next_event = dashboard_js[
        dashboard_js.index("function requestNextEvent(") :
        dashboard_js.index("function removeConnection(")
    ]
    assert "/ui/events/next" in next_event
    assert "forwardQueue" not in next_event
    assert "getJson(" not in next_event

    # The teardown has to drop queued work before the aborts, because an abort
    # completes its request and a completed request starts the next one.
    teardown = dashboard_js[
        dashboard_js.index("function stopDashboardRuntime(") :
        dashboard_js.index("function requestNextEvent(")
    ]
    assert teardown.index("forwardQueue = []") < teardown.index("connections.pop()")


def test_only_idempotent_reads_share_a_display_round_trip() -> None:
    """Two pages asking the same thing must not take the slot twice.

    Waking from standby asks /ui/state twice: the home page refreshes its
    dynamic buttons when it becomes visible, and the page being opened reads
    the same state. A read answers every caller the same way, so both are
    served from one round trip. A command must never be folded that way: it
    would be executed once and the other caller would be told it succeeded.
    """

    dashboard_js = (ROOT / "device_qml" / "js" / "c300x_ha.js").read_text(
        encoding="utf-8"
    )

    shared = dashboard_js[
        dashboard_js.index("function getJsonShared(") :
        dashboard_js.index("function forwardRequest(")
    ]
    assert "forwardActive.waiters.push(" in shared
    assert "forwardQueue[i].waiters.push(" in shared
    assert "sharedPath === path" in shared

    # getJson stays the unfolded entry point, so every command keeps its own
    # round trip.
    plain = dashboard_js[
        dashboard_js.index("function getJson(") :
        dashboard_js.index("function getJsonShared(")
    ]
    assert 'forwardRequest(path, callback, errorCallback, "")' in plain

    # Exactly the two /ui/state producers opt in: Api.status for the alarm and
    # dashboard pages, homeButtons for the patched home page.
    assert dashboard_js.count("getJsonShared(") == 3
    assert dashboard_js.count('getJsonShared("/ui/state"') == 2
    for command in ("/ui/alarm/command", "/ui/action"):
        assert f'getJsonShared("{command}' not in dashboard_js

    # An answered read must not keep collecting waiters, and one page's broken
    # handler must not silence the pages sharing the same answer.
    deliver = dashboard_js[
        dashboard_js.index("function deliverForward(") :
        dashboard_js.index("function finishForward(")
    ]
    assert deliver.index("xhr.waiters = []") < deliver.index("waiters[i].callback(")
    assert 'xhr.sharedPath = ""' in deliver
    assert deliver.count("try {") == 3
