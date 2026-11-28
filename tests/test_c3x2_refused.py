"""A Classe 300X2 is recognised and gets nothing from the installer.

The Classe 300X2 (firmware 1.2.x) runs aarch64 only, with no loader for the
armhf agent, and its display is not Qt. Before 3.1.0 the installer took it
for a Classe 300X with the Qt 4 display and went on to write. Two signs tell
it, each enough alone: the kernel's machine name aarch64 and the station's
own model name C3X2. Setup, reinstall and the SSH Repair all run this
installer; the agent update needs a running agent, which cannot exist there.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from test_agent_reinstall import _entry, _reauth_flow, _reinstall, _setup_flow
from test_installer_refuses_a_foreign_host import _Host, _install

from custom_components.bticino_c300x import config_flow, device_profile, repairs
from custom_components.bticino_c300x import device_installer as installer
from custom_components.bticino_c300x.const import CONF_REINSTALL_AGENT

ROOT = Path(__file__).resolve().parents[1]
TEXTS = ROOT / "custom_components/bticino_c300x"
REFUSED = "c3x2_not_supported"
FIRMWARE_WORK = Path(os.environ.get("C300X_FIRMWARE_WORK", ROOT.parent / "c300x-fwpatch/work"))
C3X2_ROOTFS = Path(os.environ.get("C300X_C3X2_ROOTFS", FIRMWARE_WORK / "fw-c3x2-new/rootfs-1.2.1"))
# The model file of the Classe 300X2 1.2.1, trimmed to the field read.
C3X2_MODEL = "<root>\n  <webserver_type>C3X2</webserver_type>\n  <ver_webserver>1.2.1</ver_webserver>\n</root>\n"


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from stage_device_agent_bundle import stage_bundle

    component = tmp_path / "component"
    binary = tmp_path / "agent"
    binary.write_bytes(b"offline payload; never executed")
    stage_bundle(component, version="test", skip_build=True, agent_binary=binary)
    monkeypatch.setattr(installer, "COMPONENT_DIR", component)
    return component


def _station(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, machine: str, model: str | None) -> _Host:
    """A station folder with a model file, whose uname -m answers ``machine``."""

    home = tmp_path / "home-bticino"
    home.mkdir()
    model_file = tmp_path / "dbfiles_ws.xml"
    if model is not None:
        model_file.write_text(model)
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "uname").write_text(f"#!/bin/sh\necho {machine}\n")
    (tools / "uname").chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(device_profile, "_STATION_HOME", str(home))
    monkeypatch.setattr(device_profile, "_QT5_DISPLAY_MARKER", str(tmp_path / "libQt5Core.so.5"))
    monkeypatch.setattr(device_profile, "_C100X_DISPLAY_MARKER", str(tmp_path / "BtClass100"))
    monkeypatch.setattr(device_profile, "_MODEL_FILE", str(model_file))
    host = _Host(str(tmp_path / "remote-agent"))
    monkeypatch.setattr(installer, "_connect_device_client", lambda _request: host)
    return host


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize(("machine", "model"), [
    ("aarch64", C3X2_MODEL),
    # Either sign alone is enough.
    ("aarch64", None),
    ("aarch64", "<root><webserver_type>C300X</webserver_type></root>\n"),
    ("armv7l", C3X2_MODEL),
])
def test_a_classe_300x2_gets_nothing(package, tmp_path, monkeypatch, confirmed, machine, model):
    host = _station(tmp_path, monkeypatch, machine=machine, model=model)
    with pytest.raises(installer.C300XDeviceInstallError, match=REFUSED):
        _install(tmp_path, confirmed=confirmed)
    assert host.writes == [] and host.closed
    assert not (tmp_path / "remote-agent").exists()


@pytest.mark.parametrize(("model", "c100x"), [
    ("<root><webserver_type>C300X</webserver_type></root>\n", False),
    ("<root><webserver_type>C100X</webserver_type></root>\n", True),
    (None, False),
])
def test_a_classe_300x_or_100x_is_still_admitted(package, tmp_path, monkeypatch, model, c100x):
    host = _station(tmp_path, monkeypatch, machine="armv7l", model=model)
    if c100x:
        (tmp_path / "libQt5Core.so.5").touch()
        (tmp_path / "BtClass100").touch()
    profile = installer._device_profile(host)
    assert profile.supported and profile.model == ("C100X" if c100x else "C300X")
    if not c100x:
        with pytest.raises(RuntimeError, match="reached a write"):
            _install(tmp_path, confirmed=False)
        assert host.writes == [f"mkdir -p {tmp_path / 'remote-agent'}"]


@pytest.mark.parametrize("answer", ["machine-aarch64\n", "qt4\nc300x\nnamed-C3X2\nmachine-armv7l\n",
                                    "qt4\nc300x\nmachine-aarch64\n"])
def test_the_profile_of_a_classe_300x2_offers_nothing(answer):
    profile = device_profile.station_profile(lambda _command: answer, shlex.quote)
    assert profile.model == device_profile.C3X2 and not profile.supported
    assert not profile.has_display_patch and not profile.is_c100x


@pytest.mark.parametrize("answer", ["", "machine-\n", "machine-armv7l\n", "qt5\nc100x\nmachine-armv7l\n",
                                    "qt4\nc300x\nnamed-C300X\nmachine-armv7l\n", "named-C3X\n"])
def test_an_unread_or_32_bit_answer_is_no_classe_300x2(answer):
    assert device_profile.station_profile(lambda _command: answer, shlex.quote).supported


def test_the_probe_reads_the_classe_300x2_image():
    """The probe's own command against the model file of firmware 1.2.1; the image's programs are aarch64."""

    model_file = C3X2_ROOTFS / "home/bticino/sp/dbfiles_ws.xml"
    if not model_file.is_file():
        pytest.skip("Private firmware files unavailable")

    def run(command: str) -> str:
        command = command.replace(f"'{device_profile._MODEL_FILE}'", shlex.quote(str(model_file)))
        return subprocess.run(["sh", "-c", command], capture_output=True, text=True, check=True).stdout

    assert device_profile.station_profile(run, lambda text: f"'{text}'").model == device_profile.C3X2
    # ELF e_machine 183 is AArch64: the armhf agent has no loader there.
    header = (C3X2_ROOTFS / "bin/uname.coreutils").read_bytes()[:20]
    assert header[:4] == b"\x7fELF" and int.from_bytes(header[18:20], "little") == 183
    assert (C3X2_ROOTFS / "lib/ld-linux-aarch64.so.1").is_file()
    assert not list((C3X2_ROOTFS / "lib").glob("ld-linux-armhf*"))


def test_the_ssh_repair_shows_the_refusal():
    assert repairs._ssh_install_error(installer.C300XDeviceInstallError(REFUSED)) == REFUSED


@pytest.mark.parametrize("name", ["strings.json", "translations/en.json", "translations/de.json",
                                  "translations/fr.json", "translations/it.json", "translations/es.json"])
def test_every_language_names_the_refusal(name):
    texts = json.loads((TEXTS / name).read_text(encoding="utf-8"))
    repair = texts["issues"]["device_agent_update_required"]["fix_flow"]["error"]
    assert texts["config"]["error"][REFUSED] == repair[REFUSED]
    assert "Classe 300X2" in repair[REFUSED] and "{" not in repair[REFUSED]


def test_setup_and_reinstall_show_the_installer_reason(monkeypatch):
    """Both config flow paths show the installer's reason as the form's error."""

    flow = _setup_flow(True)
    monkeypatch.setattr(config_flow, "async_ensure_installer_dependencies", AsyncMock())
    monkeypatch.setattr(config_flow, "async_install_device_agent",
                        AsyncMock(side_effect=installer.C300XDeviceInstallError(REFUSED)))
    result = asyncio.run(flow.async_step_agent_auth({CONF_REINSTALL_AGENT: True}))
    assert result["errors"] == {"base": REFUSED}
    reauth = _reauth_flow(_entry())
    result, _ = _reinstall(monkeypatch, reauth, AsyncMock(side_effect=installer.C300XDeviceInstallError(REFUSED)))
    assert result["errors"] == {"base": REFUSED}
