"""Released updaters must preserve Qt5 runtime state while installing the beta."""

import json
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest
from test_native_agent_update_legacy_bootstrap import _compile_updater

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("commit", ["v2.7.0", "v2.8.1"])
@pytest.mark.parametrize("sanitize", [False, True])
def test_released_updater_installs_beta_without_losing_display_state(
    tmp_path, monkeypatch, commit, sanitize,
):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import stage_device_agent_bundle as stager

    old = _compile_updater(tmp_path / "old", False, sanitize, commit=commit)
    current = _compile_updater(tmp_path / "new", False, sanitize)
    agent = tmp_path / "agent"
    stage = agent / ".update"
    binary = tmp_path / "synthetic-binary"
    binary.write_bytes(b"synthetic beta agent, never executed")
    stager.stage_bundle(stage, version="test", skip_build=True, agent_binary=binary)
    manifest_path = stage / "device_agent/bundle.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["update_file_set_version"] == 7

    retained = {
        "config.json": b'{"existing": "configuration"}',
        "display-qt5.rcc": b"existing resource bundle",
        "display-qt5.rcc.failed": b"existing quarantine",
        "c300x-qrc-overlay.so": b"existing extracted overlay",
        "display-qt5/vendor/HomePage.qml": b"existing original QML",
        "qml/user.qml": b"unrelated user source",
    }
    before = {}
    for relative, data in retained.items():
        target = agent / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o600)
        before[relative] = target.stat()
    recovery = tmp_path / "c300x-device-file-backups/original/bin/BtClass_qws"
    recovery.parent.mkdir(parents=True)
    recovery.write_bytes(b"original firmware wrapper backup")
    recovery.chmod(0o700)
    original_binary = agent / "c300x-agent-native"
    original_binary.write_bytes(b"previous agent")

    def apply(updater, expected=True):
        result = subprocess.run(
            [str(updater), str(agent), str(manifest_path), str(int(expected))],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    # A damaged display payload must fail before replacing the executable.
    qml = stage / "device_agent/qml/HomeAssistant.qml"
    valid_qml = qml.read_bytes()
    qml.write_bytes(valid_qml + b"\ncorrupted")
    apply(old, False)
    assert original_binary.read_bytes() == b"previous agent"
    assert not (agent / "bundle.json").exists()
    qml.write_bytes(valid_qml)
    assert apply(old)["runtime_changed"]

    for entry in manifest["files"]:
        relative = entry["path"]
        if relative == stager.LEGACY_BOOTSTRAP_QML:
            assert not (agent / "qml/C300XEnergyDistribution.qml").exists()
            continue
        if relative == "device_agent/qml/c100x_bundle.sh":
            # The Classe 100X adapter is in the package and never on a Classe 300X.
            assert not (agent / "qml/c100x_bundle.sh").exists()
            continue
        if relative == "device_agent/init/c300x-native-agent":
            target = agent / "init-script"
            expected = (stage / relative).read_bytes().replace(
                b'DEFAULT_AGENT_DIR="/home/bticino/cfg/extra/c300x-native-agent"',
                f'DEFAULT_AGENT_DIR="{agent}"'.encode(),
            ).rstrip(b"\r\n")
            assert target.read_bytes() == expected
            assert (agent / "init-link").resolve() == target
        else:
            installed = relative.removeprefix("device_agent/")
            if installed.startswith(("armhf/", "scripts/")):
                installed = Path(installed).name
            target = agent / installed
            assert sha256(target.read_bytes()).hexdigest() == entry["sha256"]
        assert target.stat().st_mode & 0o777 == (0o644 if "/qml/" in relative else 0o700)
    assert json.loads((agent / "bundle.json").read_text()) == manifest
    assert (agent / "bundle.json").stat().st_mode & 0o777 == 0o600

    # The new updater must accept the same package without rewriting files.
    assert apply(current)["changed_files"] == 0
    for relative, data in retained.items():
        target = agent / relative
        assert target.read_bytes() == data
        after = target.stat()
        assert (after.st_ino, after.st_mtime_ns, after.st_mode) == (
            before[relative].st_ino, before[relative].st_mtime_ns, before[relative].st_mode,
        )
    assert recovery.read_bytes() == b"original firmware wrapper backup"
    assert recovery.stat().st_mode & 0o777 == 0o700
    assert not list(agent.rglob("*.update-backup"))
