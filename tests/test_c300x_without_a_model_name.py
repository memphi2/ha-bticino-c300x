"""A Classe 300X whose own model name cannot be read is served like every C300X.

The station's name (``<webserver_type>``) is a second opinion next to its
display program. Missing, cut off or unknown, it says nothing: only a name
that contradicts the display program refuses the Display patch and the SSH
installer. The device agent's updater never asks for the name.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_native_device_identity import XML, station  # noqa: F401 - the fixture builds the agent's detection
from test_qml_patch_qt5 import _qt5_import_dir
from test_qml_patch_script import (
    _run_qml_patch,
    _run_qml_patch_raw,
    _write_original_gui,
)

from custom_components.bticino_c300x import device_installer as installer
from custom_components.bticino_c300x import device_profile

ROOT = Path(__file__).resolve().parents[1]
C300X_QT4 = device_profile.DeviceProfile("C300X", "qt4_ondisk", "high_res")
C300X_QT5 = device_profile.DeviceProfile("C300X", "qt5_rcc", "fixed")
# What a model file can hold without naming the station.
UNREAD = {
    "missing": None,
    "no-field": "<root><ver_webserver>1.7.19</ver_webserver></root>\n",
    "empty-field": "<root><webserver_type></webserver_type></root>\n",
    "other-name": "<root><webserver_type>F454</webserver_type></root>\n",
    "cut-off": "<root><webserver_type>C300X",
    "empty-file": "",
}
WRITES = ("core-apply", "apply", "media-user-label-apply")


def _model_file(folder: Path, content: str | None) -> Path:
    path = folder / "dbfiles_ws.xml"
    if content is not None:
        path.write_text(content)
    return path


def _files(folder: Path) -> dict[str, bytes]:
    return {str(path.relative_to(folder)): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


def _patched(tmp_path: Path, name: str, content: str | None, *, qt5: bool) -> tuple[list[object], dict[str, bytes]]:
    root = tmp_path / name
    gui, backups = root / "gui", root / "backups"
    gui.mkdir(parents=True)
    env = {"C300X_QML_DEVICE_INFO_XML": str(_model_file(root, content))}
    answers: list[object] = []
    if qt5:
        # The files of firmware 3.0.x arrive through the import; packing them needs the firmware itself.
        answers.append(_run_qml_patch(
            root, gui, backups, "qt5-import", env_overrides=env, extra_args=[str(_qt5_import_dir(root))]))
    else:
        _write_original_gui(gui)
    for action in WRITES:
        answers.append(_run_qml_patch(root, gui, backups, action, env_overrides=env))
    answers.append(_run_qml_patch(root, gui, backups, "status", env_overrides=env))
    return json.loads(json.dumps(answers).replace(str(root), "ROOT")), _files(gui)


@pytest.mark.parametrize("qt5", [False, True], ids=["qt4", "qt5"])
@pytest.mark.parametrize("case", list(UNREAD))
def test_the_display_patch_is_written_as_on_a_station_that_names_itself(tmp_path: Path, case: str, qt5: bool) -> None:
    named = _patched(tmp_path, "named", XML.format("C300X"), qt5=qt5)
    unread = _patched(tmp_path, "unread", UNREAD[case], qt5=qt5)
    assert unread == named
    assert all(isinstance(answer, dict) and answer["ok"] is True for answer in unread[0])
    assert unread[0][-1]["state"] == "patched"


@pytest.mark.parametrize("qt5", [False, True], ids=["qt4", "qt5"])
def test_only_a_contradicting_name_refuses_the_display_patch(tmp_path: Path, qt5: bool) -> None:
    gui, backups = tmp_path / "gui", tmp_path / "backups"
    gui.mkdir()
    env = {"C300X_QML_DEVICE_INFO_XML": str(_model_file(tmp_path, XML.format("C100X")))}
    imported = _qt5_import_dir(tmp_path)
    if not qt5:
        _write_original_gui(gui)
    before = _files(gui)
    for action, args in (("qt5-import", [str(imported)]), *((action, None) for action in WRITES)):
        result = _run_qml_patch_raw(tmp_path, gui, backups, action, env_overrides=env, extra_args=args)
        assert result.returncode == 3, (action, result.stdout, result.stderr)
        assert json.loads(result.stdout)["state"] == "unsupported_display"
        assert _files(gui) == before


class _LocalStation:
    """Runs the installer's read-only probe in a local shell; anything else is a write."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    def run(self, command: str, input_data: bytes | None = None) -> str:
        assert input_data is None and "webserver_type" in command, command
        self.commands.append(command)
        return subprocess.run(["sh", "-c", command], check=True, capture_output=True, text=True, timeout=10).stdout

    def put_file(self, *args: object) -> None:
        pytest.fail("Unexpected device upload")


def _station_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None, *, qt5: bool) -> None:
    qt5_marker = tmp_path / "libQt5Core.so.5"
    if qt5:
        qt5_marker.write_bytes(b"")
    monkeypatch.setattr(device_profile, "_QT5_DISPLAY_MARKER", str(qt5_marker))
    monkeypatch.setattr(device_profile, "_C100X_DISPLAY_MARKER", str(tmp_path / "BtClass100"))
    monkeypatch.setattr(device_profile, "_MODEL_FILE", str(_model_file(tmp_path, content)))


@pytest.mark.parametrize("qt5", [False, True], ids=["qt4", "qt5"])
@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("case", [*UNREAD, "named"])
def test_the_installer_admits_the_station_and_offers_its_display_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, qt5: bool, confirmed: bool,
) -> None:
    _station_files(tmp_path, monkeypatch, UNREAD.get(case, XML.format("C300X")), qt5=qt5)
    client = _LocalStation()
    profile = installer._device_profile(client)  # type: ignore[arg-type]
    assert profile == (C300X_QT5 if qt5 else C300X_QT4)
    assert profile.model_confirmed and profile.has_display_patch
    # A C300X needs neither the package's C100X marks nor a confirmation: no package is read.
    kind = installer._admit_station_sync(client, None, "/agent", confirmed)  # type: ignore[arg-type]
    assert kind == ("qt5_rcc" if qt5 else "qt4_ondisk")
    assert len(client.commands) == 2


@pytest.mark.parametrize("qt5", [False, True], ids=["qt4", "qt5"])
def test_only_a_contradicting_name_stops_the_installer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt5: bool) -> None:
    _station_files(tmp_path, monkeypatch, XML.format("C100X"), qt5=qt5)
    client = _LocalStation()
    assert not installer._device_profile(client).model_confirmed  # type: ignore[arg-type]
    with pytest.raises(installer.C300XDeviceInstallError, match="device_model_incompatible"):
        installer._admit_station_sync(client, None, "/agent", True)  # type: ignore[arg-type]


@pytest.mark.parametrize("qt5", [False, True], ids=["qt4", "qt5"])
@pytest.mark.parametrize("case", list(UNREAD))
def test_the_agent_and_home_assistant_take_the_station_as_a_c300x(station, case: str, qt5: bool) -> None:  # noqa: F811
    content = UNREAD[case]
    answer = station(xml=content, qt5="" if qt5 else None)
    kind = "qt5_rcc" if qt5 else "qt4_ondisk"
    assert (answer["model"], answer["check"], answer["display"], answer["patchable"]) == ("C300X", "unread", kind, "1")
    named = station(xml=XML.format("C300X"), qt5="" if qt5 else None)
    assert {**named, "check": "unread"} == answer
    profile = device_profile.setup_profile({"model": "C300X", "display_kind": kind, "model_check": "unread"})
    assert profile == (C300X_QT5 if qt5 else C300X_QT4)
    assert profile.model_confirmed and profile.has_display_patch


def test_the_updater_decides_by_the_model_alone() -> None:
    """The update's model question is c300x_device_model(): the name check is not part of it."""

    for name in ("agent_update.c", "agent_update.h", "agent_update_paths.h", "agent_update_firewall.c"):
        path = ROOT / "native_agent/src" / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert "model_check" not in source and "c300x_device_profile" not in source, name
        assert "MODEL_CHECK" not in source, name
    updater = (ROOT / "native_agent/src/agent_update.c").read_text(encoding="utf-8")
    assert updater.count("c300x_device_model() != C300X_DEVICE_MODEL_C100X") == 3
