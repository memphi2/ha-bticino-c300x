from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

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
    "js/c300x_ha.js",
    "js/c300x_i18n.js",
    "js/c300x_memos.js",
)
PATCH_OUTPUT_SHA256 = {
    "MainApp.qml": "b755ebd730bd5b3f7a70dc301542b21119ef4f5b88463d3bc853314609fbcad2",
    "HomePage.qml": "d17f8121d4455d0c0ca1e26c8f3a33bfca919310fef50903621eab7ee0ced5ac",
    "MemoPage.qml": "ec3b78970cd70a9ff1d48513b6658bc57323237258f4850b57bd42a5994a2e6a",
    "EventManager.qml": "1c28e909b9196909117cc58d2781d6c39a2e1d72f294786f77633050d862ad0d",
    "Alarm.qml": "e1a7bfef32000f71b386bb8e466eaf822c405e2267eca0fe3084e803901dcc3d",
    "HomeAssistant.qml": "d979051994646987fa6425736dcb7a4da7ee5354f383ecab6ab1c8cf1583075a",
    "js/c300x_ha.js": "398c522bb356dda01f246c042213c767091e84cd862c89e6eafd2519ee733520",
    "js/c300x_i18n.js": "f589b25ac7029a4d2108115d368e14628229d2ff0c3d32bdb501d88ba72ae9c9",
    "js/c300x_memos.js": "ad7138a69bb537a5e90f149a91f0e343185b7e7678054ecf5e8776dd0568cdb3",
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
    assert core_restored_status["changed_files"] == 1
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
    assert status["inhouse_state"] == "original"
    assert status["inhouse_patched"] is False
    _assert_complete_gui_patch(gui_dir)


def test_qml_inhouse_apply_installs_call_forwarding_patch(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "inhouse-apply")

    assert status["state"] == "original"
    assert status["patched"] is False
    assert status["core_state"] == "original"
    assert status["core_patched"] is False
    assert status["inhouse_state"] == "patched"
    assert status["inhouse_patched"] is True
    _assert_inhouse_gui_patch(gui_dir)


def test_qml_core_apply_installs_only_media_hook(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-apply")

    assert status["state"] == "original"
    assert status["patched"] is False
    assert status["core_state"] == "patched"
    assert status["core_patched"] is True
    assert status["changed_files"] == 1
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


def test_qml_restore_all_removes_feature_core_and_inhouse_patches(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    _run_qml_patch(tmp_path, gui_dir, backup_dir, "apply")
    _run_qml_patch(tmp_path, gui_dir, backup_dir, "inhouse-apply")
    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "restore-all")

    assert status["state"] == "original"
    assert status["patched"] is False
    assert status["core_state"] == "original"
    assert status["core_patched"] is False
    assert status["inhouse_state"] == "original"
    assert status["inhouse_patched"] is False
    assert (gui_dir / "MainApp.qml").read_text() == ORIGINAL_MAIN_APP
    assert (gui_dir / "HomePage.qml").read_text() == ORIGINAL_HOME_PAGE
    assert (gui_dir / "MemoPage.qml").read_text() == ORIGINAL_MEMO_PAGE
    assert (gui_dir / "Components/Settings/CallBlockPopup.qml").read_text() == ORIGINAL_CALL_BLOCK_POPUP
    assert (gui_dir / "EventManager.qml").read_text() == ORIGINAL_EVENT_MANAGER


def test_qml_restore_all_handles_core_only_patch(tmp_path: Path) -> None:
    gui_dir = tmp_path / "gui"
    backup_dir = tmp_path / "backups"
    gui_dir.mkdir()
    _write_original_gui(gui_dir)

    _run_qml_patch(tmp_path, gui_dir, backup_dir, "core-apply")
    status = _run_qml_patch(tmp_path, gui_dir, backup_dir, "restore-all")

    assert status["state"] == "original"
    assert status["core_state"] == "original"
    assert status["changed_files"] == 1
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

    assert 'item.hasOwnProperty("state_label")' in item_detail_body
    assert item_detail_body.index('item.hasOwnProperty("state_label")') < (
        item_detail_body.index('uiText("execute")')
    )
    assert 'source[i].hasOwnProperty("state_label")' in dashboard_items_body
    assert 'source[i].state_label || source[i].label || ""' not in dashboard_items_body


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
    assert 'request.open("GET", "http://127.0.0.1:8092/ui/media-closed", true)' in event_manager
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


def _assert_inhouse_gui_patch(gui_dir: Path) -> None:
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
