"""A Classe 300X gets from the joint package what release 2.10.0 gave it.

The joint package serves the Classe 300X on firmware 1.7.19, 2.0.2 and 3.0.6
and the Classe 100X. These tests hold the Classe 300X side to release 2.10.0:
the display files the patch writes, the agent's routes and capability answers,
and the Home Assistant entities. The texts have their own comparison in
tests/test_model_texts.py.

Every value below was produced by running the same code on release 2.10.0
(commit 04669bd2). A deliberate change for the Classe 300X is declared in the
list next to the pin it touches, or re-pinned after showing that the
difference is the intended one; it is never a side effect of Classe 100X work.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import test_qml_patch_script as patch

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native_agent"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


# --- Display files -----------------------------------------------------------

PATCH_OUTPUT_2_10_0 = {
    "MainApp.qml": "3860c9addd37ba6be61fb6eea7fa1a08d93a782ffc94c1e989341cf8ef4d53ce",
    "Settings.qml": "403b650e32e2353ba542b4960ea7d0d211d62897dbca9e953c7253e491156447",
    "Components/Settings/GeneralsChoice.qml": "fe4241e1c5d99abb9175f36ec6a9e35ef48033af0c07ab0c46b25309f615e240",
    "C300XSettings.qml": "e1bb26e8aea64ba95debd42ff2a5933fef19f09082c6606c8a9e45da997399bb",
    "js/c300x_maintenance.js": "f06a7b3ba394203ae833fadc7b13b660ee652b85b6f3b27fd96d0e353f6dc1d2",
    "HomePage.qml": "998dbd1074ab0689303d213cff46663e8b72403eb944c28a9391e35512333193",
    "MemoPage.qml": "f7fe6279108429389bc607e6c92df065d75dbbce2d9cdfc6ec1280f30f893e0f",
    "EventManager.qml": "cf68c96d9b702ce9501e70f8a511658483e1bcd5f2c9fcdff2ae214af79e3a6a",
    "Alarm.qml": "65977bf521bcdca872d3c107148ddabf7b623c4af7e6707462f62ff565ab53d0",
    "HomeAssistant.qml": "f034c5bafc1d69aa1db71f6f93ce25c2d7c2ef180b3f2cea90dc6c01079e1a3d",
    "C300XEnergy.qml": "abad8ce4ee25c49e000a44758d320afeff62d4b0964e14322a4a0cab7c90fd74",
    "C300XEnergyConsumers.qml": "def84fa2328a4d310efc1173706d513fa51e4423c825242d703a688b4768a918",
    "C300XAgenda.qml": "0853c9658d39414bb539712761052c0a08ec1c5522507ee02e749814e0e9ab3e",
    "C300XAlerts.qml": "c815a8f04aa5cc7ca51297c23477a730bcbf707bdcf6a57de8302c8e46ae0722",
    "C300XDetailControl.qml": "07b3e761c43480d763bf0c943cfe1bb8d19de794fd095bd5478609ca3ec9c42f",
    "C300XEnergyReadout.qml": "03d300c00d5685bb095b0ddf08a8964685d6f7621a2bef0f93c59546e231560e",
    "C300XEnergySums.qml": "d69adc8a62deceaa27b7329b32827b991b1d8152476d4e2298c498558c295585",
    "C300XLeaveHome.qml": "5e345c456aa7ef10f82388d55947b70501b6fe38d43c9a23cb40e14a2240682d",
    "C300XChecks.qml": "04f543caca11a04449b9cedff97e3e3b244e2ec5aec4ed004fd0a2eee2a6d399",
    "C300XSituations.qml": "c6a461eb725c588db864559b31430546387948c3f39e3de502dc23e797c4b48b",
    "C300XOptionalPages.qml": "652645890db10c3797a9f11a165c1ff10faff1bc89164864921b9c3e94444a4d",
    "C300XPageNavigation.qml": "958aee89fe169d819c3abfd94cfecac0a2fb335845303282100f35b9f52ea638",
    "C300XRingerControl.qml": "18fd4869c4041c53078619da1e846aaeb599a59fdae4154499c861da7ff6740b",
    "js/c300x_alerts.js": "a06a136e24ba269ee49110d7586c5fb97deda137371e2f8a52a93696ec3ff3d1",
    "js/c300x_energy.js": "2c870b4e39fb41718421394f4afa35df8116e9ae247031a688f831506a823af2",
    "js/c300x_energy_consumers.js": "f4128432b1990bebb79eae88daafe54481e953ad621fcf758e685ad57f0b4377",
    "js/c300x_ringer.js": "268fed06c44704de8fbf04ec458cac7425b9fbc78f9a68514112ca751603cb71",
    "js/c300x_ha.js": "40c83a7d5baffae75819a134657ca89ffe1e81194f5bb26a7533e13a401df0f5",
    "js/c300x_i18n.js": "2f1149d6ed2917d9819a742294b3e373894b1f7f97181641fbaac31aad685d14",
    "js/c300x_memos.js": "2e922d5617dfafda1c231581ef1eff46f83f4897a11a7350926641135c46040d",
}

SIDE_BY_SIDE_2_10_0 = "5dc87a9ad493adcc11e4515f139a4545f1f103cbdd9f0526ceecb3c3b4a9cdb3"
# Output files whose content was changed on purpose after 2.10.0.
PATCH_OUTPUT_CHANGED: frozenset[str] = frozenset()
PATCH_OUTPUT_ADDED: frozenset[str] = frozenset()


def test_the_patch_writes_the_display_files_of_2_10_0() -> None:
    current = patch.PATCH_OUTPUT_SHA256
    assert set(current) - PATCH_OUTPUT_ADDED == set(PATCH_OUTPUT_2_10_0)
    differing = {name for name, pin in PATCH_OUTPUT_2_10_0.items() if current[name] != pin}
    assert differing == PATCH_OUTPUT_CHANGED
    assert patch.SIDE_BY_SIDE_HOME_PAGE_SHA256 == SIDE_BY_SIDE_2_10_0


def test_the_shared_display_sources_do_not_name_a_model() -> None:
    """The Classe 100X pages live in their own directory; nothing shared was touched for them."""

    shared = [path for path in (ROOT / "device_qml").rglob("*")
              if path.is_file() and "c100x" not in path.relative_to(ROOT / "device_qml").parts]
    assert shared
    for path in shared:
        if path.suffix in {".qml", ".js"}:
            assert "c100x" not in path.read_text(encoding="utf-8").lower(), path


# The whole display patch on copies of the real skins: every file it leaves
# after apply and after restore, its backups and each answer of the script.
FIRMWARE_PATCH_2_10_0 = {
    "1.7.19": "2c1231858c338b1d4eedeb725355e661035c46d81c2e993e744cfcc15d6ef147",
    "2.0.2": "2c1231858c338b1d4eedeb725355e661035c46d81c2e993e744cfcc15d6ef147",
    "3.0.6": "a94d01782f4bbf75f30331e0dad42f73efb6677e3c9132204cf517af5acc4513",
}


def _skin(firmware: str) -> Path | None:
    work = os.environ.get("C300X_FIRMWARE_WORK")
    if firmware == "3.0.6":
        skin = os.environ.get("C300X_QT5_SKIN")
        return Path(skin) if skin else None
    return Path(work) / f"rootfs-{firmware}/home/bticino/bin/gui/skins/default" if work else None


def _files(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def firmware_patch_record(skin: Path, top: Path, *, qt5: bool) -> dict[str, object]:
    gui, backups = top / "gui", top / "backups"
    answers = []
    if qt5:
        gui.mkdir()
        answers.append(patch._run_qml_patch(top, gui, backups, "qt5-import", extra_args=[str(skin)]))
    else:
        shutil.copytree(skin, gui)
    for action in ("core-apply", "apply", "status"):
        answers.append(patch._run_qml_patch(top, gui, backups, action))
    applied = _files(gui)
    for action in ("restore", "core-restore", "restore-all", "status"):
        answers.append(patch._run_qml_patch(top, gui, backups, action))
    return {"applied": applied, "restored": _files(gui), "backups": _files(backups),
            "answers": [json.loads(json.dumps(answer).replace(str(top), "<TMP>")) for answer in answers]}


@pytest.mark.parametrize("firmware", sorted(FIRMWARE_PATCH_2_10_0))
def test_the_patch_on_the_real_skin_is_byte_identical_to_2_10_0(firmware: str, tmp_path: Path) -> None:
    skin = _skin(firmware)
    if skin is None or not skin.is_dir():
        pytest.skip(f"firmware {firmware} skin not available (C300X_FIRMWARE_WORK, C300X_QT5_SKIN)")
    record = firmware_patch_record(skin, tmp_path, qt5=firmware == "3.0.6")
    assert [answer.get("state") for answer in record["answers"]][-6:-4] == ["patched", "patched"]
    assert _digest(record) == FIRMWARE_PATCH_2_10_0[firmware]


# --- Agent routes ------------------------------------------------------------

ROUTES_2_10_0 = (
    "/api/v1/activations",
    "/api/v1/activations/",
    "/api/v1/announcements",
    "/api/v1/answering-machine",
    "/api/v1/answering-machine/messages",
    "/api/v1/answering-machine/messages/",
    "/api/v1/answering-machine/messages/actions/delete",
    "/api/v1/calls/doorbell",
    "/api/v1/calls/doorbell/actions/answer",
    "/api/v1/calls/doorbell/actions/capture",
    "/api/v1/calls/doorbell/actions/hangup",
    "/api/v1/calls/doorbell/status",
    "/api/v1/calls/home",
    "/api/v1/calls/home/actions/start",
    "/api/v1/calls/home/actions/stop",
    "/api/v1/calls/home/status",
    "/api/v1/capabilities",
    "/api/v1/device-user",
    "/api/v1/diagnostics",
    "/api/v1/display/alert",
    "/api/v1/display-bridge",
    "/api/v1/display-bridge/events",
    "/api/v1/display/touch-tone",
    "/api/v1/events/recent",
    "/api/v1/events/subscriptions",
    "/api/v1/events/subscriptions/",
    "/api/v1/health",
    "/api/v1/identity/proof",
    "/api/v1/locks/",
    "/api/v1/maintenance/",
    "/api/v1/maintenance/agent/actions/remove",
    "/api/v1/maintenance/agent/actions/restart",
    "/api/v1/maintenance/audio-codec",
    "/api/v1/maintenance/audio-codec/actions/apply",
    "/api/v1/maintenance/audio-codec/actions/restore",
    "/api/v1/maintenance/auth",
    "/api/v1/maintenance/camera-quality",
    "/api/v1/maintenance/camera-resolution",
    "/api/v1/maintenance/config/actions/normalize",
    "/api/v1/maintenance/device-user/actions/ensure-homeassistant",
    "/api/v1/maintenance/device-user/actions/restore-homeassistant-setup",
    "/api/v1/maintenance/firewall",
    "/api/v1/maintenance/firewall/actions/apply",
    "/api/v1/maintenance/firewall/actions/restore",
    "/api/v1/maintenance/gui/actions/reload",
    "/api/v1/maintenance/ipv6-firewall",
    "/api/v1/maintenance/ipv6-firewall/actions/apply",
    "/api/v1/maintenance/ipv6-firewall/actions/restore",
    "/api/v1/maintenance/legacy-mqtt",
    "/api/v1/maintenance/mqtt",
    "/api/v1/maintenance/mqtt/actions/migrate-legacy",
    "/api/v1/maintenance/qml-patch",
    "/api/v1/maintenance/qml-patch/actions/apply",
    "/api/v1/maintenance/qml-patch/actions/apply-core",
    "/api/v1/maintenance/qml-patch/actions/restore",
    "/api/v1/maintenance/qml-patch/actions/restore-core",
    "/api/v1/maintenance/reboot",
    "/api/v1/maintenance/ssh",
    "/api/v1/maintenance/ssh/actions/start",
    "/api/v1/maintenance/ssh/actions/stop",
    "/api/v1/maintenance/update/apply",
    "/api/v1/maintenance/update/file",
    "/api/v1/maintenance/update/prepare",
    "/api/v1/maintenance/update/status",
    "/api/v1/memos",
    "/api/v1/memos/actions/delete",
    "/api/v1/memos/text/actions/create",
    "/api/v1/memos/voice/",
    "/api/v1/ringer",
    "/api/v1/self-test",
    "/api/v1/smartphone-forwarding",
    "/api/v1/stair-light/actions/activate",
    "/api/v1/state",
    "/api/v1/system/metrics",
    "/api/v1/video/doorbell",
    "/api/v1/video/doorbell/actions/activate",
    "/api/v1/video/doorbell/actions/stop",
    "/api/v1/video/doorbell/audio",
    "/api/v1/video/doorbell/snapshot",
    "/api/v1/video/doorbell/status",
    "/api/v1/video/picture",
    "/ui/action",
    "/ui/alarm/command",
    "/ui/alarm/status",
    "/ui/alerts/next",
    "/ui/answering-machine/messages",
    "/ui/events/next",
    "/ui/events/status",
    "/ui/maintenance",
    "/ui/maintenance/reboot",
    "/ui/maintenance/remove",
    "/ui/maintenance/ssh",
    "/ui/media-closed",
    "/ui/memos",
    "/ui/preferences",
    "/ui/ringer/next",
    "/ui/state",
    "/ui/status",
    "/ui/touch-tone/next",
    "/ui/touch-tone/state",
)
# Paths the joint agent knows in addition. On a Classe 300X the first is the
# prefix of answering-machine paths 2.10.0 already served; the others answer
# only on a Classe 100X.
ROUTES_ADDED = frozenset({
    "/api/v1/answering-machine/",
    "/api/v1/maintenance/c100x-display",
    "/ui/c100x/presence/next",
    "/ui/c100x/presence/probe",
    "/ui/c100x/presence/status",
    # 3.1.0: outdoor units and calls, see docs/dev/multi-outdoor-units.md.
    "/api/v1/calls",
    "/api/v1/calls/",
    "/api/v1/outdoor-units",
    "/api/v1/outdoor-units/",
})
# 3.1.0: answer and hang-up name the call (/api/v1/calls/{call_id}/actions/...).
ROUTES_REMOVED = frozenset({
    "/api/v1/calls/doorbell/actions/answer",
    "/api/v1/calls/doorbell/actions/hangup",
})
_ROUTE = re.compile(r'"(/(?:api/v1|ui)/[A-Za-z0-9_/.{}-]*)"')


def test_the_agent_serves_every_route_of_2_10_0() -> None:
    current = set()
    for source in (NATIVE / "src").glob("*.c"):
        current.update(_ROUTE.findall(source.read_text(encoding="utf-8")))
    assert set(ROUTES_2_10_0) - current == ROUTES_REMOVED
    assert current - set(ROUTES_2_10_0) == ROUTES_ADDED


# --- Capability answers ------------------------------------------------------

# Members of "device" the joint agent adds; nothing else may differ.
CAPABILITIES_ADDED_DEVICE = frozenset({"display_kind", "camera", "model_check", "board", "article"})
# The five documents of the 2.10.0 driver, without the update file set version
# (6 there, 7 here: the joint agent carries the Classe 100X adapter).
CAPABILITIES_2_10_0 = "a53a8cf1ff370621b7529c308b6a9cd8e7bf465b766544c0f9f6a5a688038451"


def c300x_capability_documents(folder: Path, display_kind: str) -> list[dict]:
    binary = folder / "capabilities-c300x"
    if not binary.exists():
        subprocess.run(
            ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
             str(NATIVE / "test/capabilities_c300x_test.c"),
             *[str(NATIVE / "src" / name) for name in (
                 "capabilities.c", "answering_capabilities.c", "json_util.c", "json_parse.c")],
             "-o", str(binary)],
            check=True, capture_output=True, text=True,
        )
    result = subprocess.run([str(binary), display_kind], check=True, capture_output=True, text=True)
    return [json.loads(line) for line in result.stdout.splitlines()]


@pytest.mark.parametrize("display_kind", ["qt4_ondisk", "qt5_rcc"])
def test_a_c300x_answers_capabilities_as_2_10_0(tmp_path: Path, display_kind: str) -> None:
    documents = c300x_capability_documents(tmp_path, display_kind)
    assert len(documents) == 5
    for document in documents:
        device = document["device"]
        assert set(device) >= CAPABILITIES_ADDED_DEVICE
        assert (device["model"], device["display_kind"]) == ("C300X", display_kind)
        for name in CAPABILITIES_ADDED_DEVICE:
            del device[name]
        assert document["agent"].pop("self_update_file_set_version") == 7
        assert "c100x_display" not in document["capabilities"]
        # 3.1.0: API version 2 with outdoor units and calls; nothing else differs.
        assert document["api_version"] == document["agent"]["api_version"] == "2"
        document["api_version"] = document["agent"]["api_version"] = "1"
        capabilities = document["capabilities"]
        assert capabilities.pop("outdoor_units") is True and capabilities.pop("calls") is True
        capabilities["call_events"] = False
    assert hashlib.sha256(
        json.dumps(documents, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest() == CAPABILITIES_2_10_0


# --- Home Assistant entities -------------------------------------------------

PLATFORMS = ("binary_sensor", "button", "camera", "event", "media_player", "number", "select", "sensor", "switch")
# Per capability document: class, unique id, translation key, category,
# enabled by default and device class of every entity of every platform.
ENTITIES_2_10_0 = (
    "7904cb1d87bc83c2c698d68a1b439cfff13a547cb1fdca536c0e01d7017ba1c7",
    "7904cb1d87bc83c2c698d68a1b439cfff13a547cb1fdca536c0e01d7017ba1c7",
    "4750a2ff30f8754c1ea3e1c073b62c93003ff380e81b18133e1ce99d4db54574",
    "4750a2ff30f8754c1ea3e1c073b62c93003ff380e81b18133e1ce99d4db54574",
    "ee84699b53d0d7597a5e7a1858dc07a35d8a04753a0ecabb5cbb75ee35e07ae0",
)
ENTITY_COUNTS_2_10_0 = (37, 37, 40, 40, 28)


def _entry(document: dict) -> MagicMock:
    runtime = MagicMock()
    runtime.capabilities = document["capabilities"]
    runtime.setup_info = {"device_id": "station", **document["device"],
                          "version": document["agent"].get("version", ""), "agent": document["agent"]}
    runtime.api = AsyncMock()
    entry = MagicMock()
    entry.entry_id = "entry"
    entry.unique_id = "station"
    entry.title = "Door"
    entry.data = {"host": "station.invalid", "port": 8091, "name": "Door", "video_enabled": True,
                  "model": document["device"]["model"]}
    entry.options = {}
    entry.runtime_data = runtime
    return entry


def _collector(found: list):
    def add(entities, *_args, **_kwargs) -> None:
        found.extend(entities)

    return add


def _attribute(entity: object, name: str) -> str | None:
    try:
        value = getattr(entity, name)
    except Exception:  # noqa: BLE001
        return "?"
    return None if value is None or isinstance(value, MagicMock) else str(value)


async def entity_inventory(document: dict) -> dict[str, list[list[str | None]]]:
    inventory = {}
    for platform in PLATFORMS:
        module = importlib.import_module(f"custom_components.bticino_c300x.{platform}")
        found: list = []
        hass = MagicMock()
        hass.data = {}
        await module.async_setup_entry(hass, _entry(document), _collector(found))
        inventory[platform] = sorted(
            ([type(entity).__name__, *[_attribute(entity, name) for name in (
                "unique_id", "translation_key", "entity_category",
                "entity_registry_enabled_default", "device_class")]] for entity in found),
            key=json.dumps,
        )
    return inventory


@pytest.mark.parametrize("display_kind", ["qt4_ondisk", "qt5_rcc"])
def test_a_c300x_gets_the_entities_of_2_10_0(tmp_path: Path, display_kind: str) -> None:
    documents = c300x_capability_documents(tmp_path, display_kind)
    for document, pin, count in zip(documents, ENTITIES_2_10_0, ENTITY_COUNTS_2_10_0, strict=True):
        inventory = asyncio.run(entity_inventory(document))
        assert sum(len(rows) for rows in inventory.values()) == count
        assert _digest(inventory) == pin
