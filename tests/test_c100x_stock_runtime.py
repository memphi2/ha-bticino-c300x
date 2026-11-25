"""The adapter inside the original C100X main.qml on host Qt 5, driven by keys.

Optional: needs host PyQt5 and the private extracted firmware (never in the
repository). The agent is an in-memory reply table and every request URL is
recorded, so a request that could not reach the agent fails the scenario.
Host Qt 5.15 with vendor stand-ins is not the firmware runtime or a device.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_scenario(name, tmp_path, firmware=True, arguments=()):
    if importlib.util.find_spec("PyQt5") is None:
        pytest.skip("Optional host PyQt5 absent; not a firmware-runtime test")
    from test_native_routing_firmware_restore import FIRMWARE_ROOT, original
    if firmware:
        original("c100x-1.5.8")
    skin = FIRMWARE_ROOT / "rootfs-c100x-1.5.8/home/bticino/bin/gui/skins/default"
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests/fixtures/c100x_stock_scenarios.py"), name, str(tmp_path), str(skin), *arguments],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software",
             "QML_DISABLE_DISK_CACHE": "1", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
        capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


def test_bridge_declares_the_agent_ui_listener():
    bridge = (ROOT / "device_qml/c100x/C100XBridge.qml").read_text()
    assert '    readonly property string uiBaseUrl: "http://127.0.0.1:8090"\n' in bridge
    # The agent refuses to activate the adapter on any other UI port.
    api = (ROOT / "native_agent/src/http_c100x_display_api.c").read_text()
    assert 'config->ui_port != 8090' in api and '"c100x_display_ui_port_unsupported"' in api


def test_bridge_requests_reach_the_agent_listener(tmp_path):
    run_scenario("bridge_urls", tmp_path)


def test_action_survives_a_click_that_unloads_it(tmp_path):
    run_scenario("action_destroyed_by_click", tmp_path, firmware=False)


@pytest.mark.parametrize("scenario", ["settings_status_item", "settings_without_bridge"])
def test_status_messages_item_in_the_vendor_settings_carousel(tmp_path, scenario):
    run_scenario(scenario, tmp_path)


@pytest.mark.parametrize("flags", ["0000", "0111", "1001", "1110"])
def test_carousel_entries_keep_the_vendor_index_rules(tmp_path, flags):
    # Netatmo camera, auto-open allowed, dashboard available, Alarmo configured. Each start state
    # walks through all 16 combinations at runtime, beside the unpatched vendor page doing the same.
    run_scenario("menu_combinations", tmp_path, arguments=tuple(flags))


@pytest.mark.parametrize("scenario", ["menu_entries_open_their_pages", "menu_entries_retry_without_polling"])
def test_carousel_entries(tmp_path, scenario):
    run_scenario(scenario, tmp_path)


def test_identity_helper_knows_the_shipped_hooks():
    import hashlib
    identity = (ROOT / "native_agent/scripts/c100x_display_identity.sh").read_text()
    for name, variable in (("main.inc", "MAIN_HOOK_SHA"), ("menu.inc", "MENU_HOOK_SHA")):
        digest = hashlib.sha256((ROOT / "device_qml/c100x/hooks" / name).read_bytes()).hexdigest()
        assert f"\n{variable}={digest}\n" in identity


@pytest.mark.parametrize("scenario", ["dashboard_navigation", "detail_controls", "alarmo_page"])
def test_pages_are_operated_like_the_vendor_menus(tmp_path, scenario):
    run_scenario(scenario, tmp_path)


def test_alert_covers_the_screen_and_shows_its_action(tmp_path):
    run_scenario("alert_covers_the_screen", tmp_path)


@pytest.mark.parametrize("arguments", [
    ("alert_dismissed_returns_the_keys", "menu"), ("alert_dismissed_returns_the_keys", "page"),
    ("alert_then_call", "menu"), ("alert_then_call", "page"),
    ("alert_screen_off_on_page",), ("alert_adapter_stops",), ("alert_during_call",),
], ids=" ".join)
def test_keys_work_after_a_notice(tmp_path, arguments):
    # The notice borrows the window focus from the vendor's scope; whatever ends it (Mark read, a call,
    # the screen going off, the adapter stopping), the vendor's current page must have the keys again.
    run_scenario(arguments[0], tmp_path, arguments=arguments[1:])


@pytest.mark.parametrize("cause", ["missing", "unnamed"])
def test_a_screen_without_a_page_shows_exit(tmp_path, cause):
    run_scenario("screen_without_page", tmp_path, arguments=(cause,))
